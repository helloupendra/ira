"""The daemon: holds this Mac's WebSocket to the IRA server and answers its calls.

* Says hello with the tools, waits for welcome, then answers each ``call``
  with a ``result`` (several at once), and pings every 30 seconds.
* Hears nothing for 90 seconds: drops the connection and reconnects.
* Reconnects with a growing delay (1 s up to 60 s, with jitter); after a
  revoked or unknown token it waits 5 minutes between tries and says why.
* Events (a watched tab finished) wait in an outbox and go out at most one per
  30 seconds, the server's limit; a reconnect does not lose them.
* Observations (the routine skill: lock, sleep, wake, network) wait in their
  own queue while offline and go out as soon as it is connected again.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ira_mac import __version__, tls
from ira_mac.tools import Toolbox, ToolFailed

log = logging.getLogger("ira_mac.daemon")

PING_SECONDS = 30.0
SILENCE_SECONDS = 90.0
EVENT_SECONDS = 31.0  # the server allows one per 30 s; a second to spare
BACKOFF = (1, 2, 5, 10, 30, 60)
REFUSED_WAIT = 300.0
MAX_FRAME = 1024 * 1024
STABLE_SECONDS = 60.0  # a connection that lasted this long resets the backoff

# Close codes from the server.
UNAUTHORIZED = {4401, 4403}

# connect(url, token) -> an open WebSocket with send(), recv() and close().
Connect = Callable[[str, str], Awaitable[Any]]


async def websocket_connect(url: str, token: str) -> Any:
    """Open the device WebSocket with the token in a header (never in the URL)."""
    from websockets.asyncio.client import connect

    secure = {"ssl": tls.context()} if url.startswith("wss://") else {}
    return await connect(
        url,
        additional_headers={"Authorization": f"Bearer {token}"},
        max_size=MAX_FRAME,
        ping_interval=None,  # the protocol's own ping frames keep it alive
        user_agent_header=f"ira-mac/{__version__}",  # Cloudflare refuses Python's default
        open_timeout=20,
        **secure,
    )


def close_code(exc: BaseException) -> int | None:
    """The close code a closed connection or a refused handshake carries, if any."""
    for attr in ("rcvd", "sent"):
        frame = getattr(exc, attr, None)
        code = getattr(frame, "code", None)
        if code is not None:
            return int(code)
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status in (401, 403):
        return 4401
    return None


class Daemon:
    def __init__(
        self,
        url: str,
        token: Callable[[], str | None],
        tools: Toolbox,
        *,
        label: str = "My Mac",
        connect: Connect = websocket_connect,
        ping_seconds: float = PING_SECONDS,
        silence_seconds: float = SILENCE_SECONDS,
        event_seconds: float = EVENT_SECONDS,
        backoff: tuple[float, ...] = BACKOFF,
        refused_wait: float = REFUSED_WAIT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.url = url
        self.token = token
        self.tools = tools
        self.label = label
        self.connect = connect
        self.ping_seconds = ping_seconds
        self.silence_seconds = silence_seconds
        self.event_seconds = event_seconds
        self.backoff = backoff
        self.refused_wait = refused_wait
        self.clock = clock
        self.outbox: collections.deque[dict[str, Any]] = collections.deque(maxlen=50)
        self.observations: collections.deque[dict[str, Any]] = collections.deque(maxlen=500)
        self._outbox_ready = asyncio.Event()
        self._last_event: float | None = None
        self.device_id: int | None = None
        self.skills: list[str] = []
        self.connected = asyncio.Event()
        self._stop = asyncio.Event()
        self._ws: Any = None
        self._closing: asyncio.Task[Any] | None = None

    # Events from the tools.

    def announce(self, event: str, title: str, text: str, data: dict[str, Any]) -> None:
        self.outbox.append(
            {"type": "event", "event": event, "title": title, "text": text, "data": data}
        )
        self._outbox_ready.set()

    def observe(self, frame: dict[str, Any]) -> None:
        """Queue an observation (from any thread); it goes out when connected."""
        self.observations.append(frame)
        loop = getattr(self, "_loop", None)
        if loop is not None:
            loop.call_soon_threadsafe(self._outbox_ready.set)

    # The connection.

    def hello(self) -> dict[str, Any]:
        return {
            "type": "hello",
            "kind": "mac",
            "label": self.label,
            "version": __version__,
            "tools": self.tools.definitions,
        }

    def stop(self) -> None:
        """Stop for good: close the connection now and do not reconnect."""
        self._stop.set()
        if self._ws is not None:
            self._closing = asyncio.ensure_future(self._ws.close())

    async def run_forever(self) -> None:
        self._loop = asyncio.get_running_loop()
        attempt = 0
        while not self._stop.is_set():
            token = self.token()
            if not token:
                log.warning("no device token in the Keychain: pair this Mac again")
                await self._sleep(self.refused_wait)
                continue
            started = self.clock()
            code = await self.run_once(token)
            if self._stop.is_set():
                return
            if code in UNAUTHORIZED:
                log.warning(
                    "the server refused this Mac's token (%s): it was revoked or never paired; "
                    "pair again from the Devices page",
                    code,
                )
                await self._sleep(self.refused_wait)
                attempt = 0
                continue
            if self.clock() - started >= STABLE_SECONDS:
                attempt = 0
            delay = self.backoff[min(attempt, len(self.backoff) - 1)]
            attempt += 1
            delay *= random.uniform(0.8, 1.2)
            log.info("reconnecting in %.0fs", delay)
            await self._sleep(delay)

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._stop.wait(), seconds)

    async def run_once(self, token: str) -> int | None:
        """One connection, from hello until it closes. Returns the close code, if any."""
        try:
            ws = await self.connect(self.url, token)
        except Exception as exc:
            code = close_code(exc)
            log.warning("could not connect: %s", tls.reason(exc))
            return code
        self._ws = ws
        if self._stop.is_set():
            await ws.close()
            return None
        try:
            await ws.send(json.dumps(self.hello()))
            welcome = json.loads(await asyncio.wait_for(ws.recv(), self.silence_seconds))
            if welcome.get("type") != "welcome":
                log.warning("the server refused the hello: %s", str(welcome.get("error"))[:200])
                return None
            self.device_id = welcome.get("deviceId")
            self.skills = list(welcome.get("skills") or [])
            log.info("connected as device %s with skills %s", self.device_id, self.skills)
            self.connected.set()
            return await self._session(ws)
        except Exception as exc:
            code = close_code(exc)
            log.info("connection ended: %s %s", type(exc).__name__, code or "")
            return code
        finally:
            self._ws = None
            self.connected.clear()
            with contextlib.suppress(Exception):
                await ws.close()

    async def _session(self, ws: Any) -> int | None:
        lock = asyncio.Lock()

        async def send(frame: dict[str, Any]) -> None:
            data = json.dumps(frame, ensure_ascii=False)
            if len(data.encode()) > MAX_FRAME:
                frame = {
                    "type": "result",
                    "id": frame.get("id"),
                    "ok": False,
                    "error": "the answer was larger than 1 MB",
                }
                data = json.dumps(frame)
            async with lock:
                await ws.send(data)

        calls: set[asyncio.Task[None]] = set()

        async def answer(frame: dict[str, Any]) -> None:
            call_id, name = frame.get("id"), str(frame.get("tool"))
            started = time.monotonic()
            try:
                content = await self.tools.call(name, frame.get("args") or {})
                reply = {"type": "result", "id": call_id, "ok": True, "content": content}
            except ToolFailed as exc:
                reply = {"type": "result", "id": call_id, "ok": False, "error": str(exc)}
            except Exception as exc:  # the bridge and anything unexpected
                reply = {"type": "result", "id": call_id, "ok": False, "error": str(exc)[:300]}
            log.info(
                "%s %s in %.2fs",
                name,
                "ok" if reply["ok"] else "failed",
                time.monotonic() - started,
            )
            with contextlib.suppress(Exception):
                await send(reply)

        async def pinger() -> None:
            while True:
                await asyncio.sleep(self.ping_seconds)
                await send({"type": "ping"})

        async def sender() -> None:
            while True:
                while self.observations:
                    await send(self.observations[0])
                    self.observations.popleft()
                if not self.outbox:
                    self._outbox_ready.clear()
                    if self.observations:
                        continue
                    await self._outbox_ready.wait()
                    continue
                if self._last_event is not None:
                    wait = self.event_seconds - (self.clock() - self._last_event)
                    if wait > 0:
                        await asyncio.sleep(wait)
                frame = self.outbox[0]
                await send(frame)
                self.outbox.popleft()
                self._last_event = self.clock()
                log.info("sent event %s", frame["event"])

        helpers = [asyncio.create_task(pinger()), asyncio.create_task(sender())]
        try:
            while True:
                try:
                    text = await asyncio.wait_for(ws.recv(), self.silence_seconds)
                except asyncio.TimeoutError:
                    log.warning("heard nothing for %.0fs; reconnecting", self.silence_seconds)
                    return None
                try:
                    frame = json.loads(text)
                except ValueError:
                    continue
                kind = frame.get("type") if isinstance(frame, dict) else None
                if kind == "call":
                    task = asyncio.create_task(answer(frame))
                    calls.add(task)
                    task.add_done_callback(calls.discard)
                elif kind == "ping":
                    await send({"type": "pong"})
                elif kind == "skills":
                    self.skills = [str(s) for s in frame.get("skills") or []]
                    log.info("skills now %s", self.skills)
                elif kind == "error":
                    log.warning("the server said: %s", str(frame.get("error"))[:200])
        finally:
            for task in [*helpers, *calls]:
                task.cancel()
            for task in [*helpers, *calls]:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
