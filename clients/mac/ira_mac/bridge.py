"""The daemon's side of Chrome: a Unix socket the native-messaging host connects to.

Chrome starts the host (``in.ira.mac``) when the Ira extension connects to it;
the host relays frames between Chrome and this socket. Requests go to the
extension with an ``id``; its answers come back with the same ``id``.

The socket lives in a folder only this user can open (mode 0700).
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import os
import time
from pathlib import Path
from typing import Any

from ira_mac.frames import FrameError, encode, read_frame_async

log = logging.getLogger("ira_mac.bridge")

REQUEST_SECONDS = 15.0


class BridgeError(RuntimeError):
    """Chrome could not answer; the message is safe to show."""


class ChromeBridge:
    def __init__(self, path: Path, *, request_seconds: float = REQUEST_SECONDS) -> None:
        self.path = path
        self.request_seconds = request_seconds
        self._server: asyncio.base_events.Server | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._ids = itertools.count(1)
        self.extension_version: str | None = None

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()
        self._server = await asyncio.start_unix_server(self._serve, path=str(self.path))
        os.chmod(self.path, 0o600)

    async def stop(self) -> None:
        # Close the host's connection first: from Python 3.12, wait_closed() waits for it.
        if self._writer is not None:
            self._writer.close()
        self._fail("the companion stopped")
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 2)
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()

    def _fail(self, reason: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(BridgeError(reason))
        self._pending.clear()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """One host connection. A newer one takes over: one Chrome profile at a time."""
        if self._writer is not None:
            self._writer.close()
            self._fail("Chrome reconnected")
        self._writer = writer
        log.info("Chrome connected")
        with contextlib.suppress(ConnectionError):
            writer.write(encode({"type": "status", "ready": True}))
            await writer.drain()
        try:
            while True:
                message = await read_frame_async(reader)
                if message is None:
                    break
                self._handle(message)
        except (FrameError, ConnectionError) as exc:
            log.warning("Chrome connection ended: %s", type(exc).__name__)
        finally:
            if self._writer is writer:
                self._writer = None
                self._fail("Chrome disconnected")
            writer.close()
            log.info("Chrome disconnected")

    def _handle(self, message: Any) -> None:
        if not isinstance(message, dict):
            return
        if message.get("type") == "hello":
            self.extension_version = str(message.get("extension") or "")[:20] or None
            return
        future = self._pending.get(message.get("id"))  # type: ignore[arg-type]
        if future is None or future.done():
            return
        if message.get("ok") is True:
            future.set_result(message.get("result"))
        else:
            future.set_exception(BridgeError(str(message.get("error") or "Chrome failed")[:300]))

    async def request(self, op: str, **fields: Any) -> Any:
        """Ask the extension to do one thing; its result, or BridgeError."""
        writer = self._writer
        if writer is None or writer.is_closing():
            raise BridgeError(
                "Chrome is not connected: open Chrome, and check that the Ira extension is on"
            )
        request_id = next(self._ids)
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        started = time.monotonic()
        try:
            writer.write(encode({"id": request_id, "op": op, **fields}))
            await writer.drain()
            return await asyncio.wait_for(future, self.request_seconds)
        except asyncio.TimeoutError:
            raise BridgeError(
                f"Chrome did not answer within {self.request_seconds:g} seconds"
            ) from None
        except ConnectionError:
            raise BridgeError("Chrome disconnected") from None
        finally:
            self._pending.pop(request_id, None)
            log.info("chrome %s took %.2fs", op, time.monotonic() - started)
