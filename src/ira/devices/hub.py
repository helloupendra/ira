"""Live device connections: calls to a device, its answers, its events, and its tools.

One connection per device: a new one replaces the old, whose calls fail. A
call waits 25 seconds at most, and a device has at most four in flight.
Both sides ping every 30 seconds; 90 seconds of silence closes the
connection. A device announces at most one event per 30 seconds.

A device's tools are offered only to its own user, and only while the skill
they belong to is switched on. Its events reach only that user: their web
app, their Telegram chats and their Android devices.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ira.devices.protocol import (
    CALL_SECONDS,
    CLOSE_BAD_HELLO,
    CLOSE_REPLACED,
    CLOSE_REVOKED,
    CLOSE_SILENT,
    CLOSE_TOO_BIG,
    EVENT_SECONDS,
    HELLO_SECONDS,
    MAX_FRAME_BYTES,
    MAX_IN_FLIGHT,
    PING_SECONDS,
    SILENCE_SECONDS,
    DeviceTool,
    Event,
    ProtocolError,
    clean_line,
    decode,
    encode,
    parse_event,
    parse_hello,
)
from ira.devices.store import Device, Devices
from ira.tools.actions import PendingAction
from ira.tools.personal import PersonalTool
from ira.tools.registry import ToolError

log = logging.getLogger("ira.devices")

MAX_ERROR = 500
LISTENER_QUEUE = 100


class Socket(Protocol):
    """What the hub needs from a WebSocket (Starlette's has these)."""

    async def receive_text(self) -> str: ...

    async def send_text(self, data: str) -> None: ...

    async def close(self, code: int = 1000, reason: str | None = None) -> None: ...


# Told about each event, for a channel such as Telegram: (user id, the stored event).
Notifier = Callable[[int, dict[str, Any]], Awaitable[None]]
# Takes a device's observe frame for learning: (user id, device id, frame).
Observer = Callable[[int, int, dict[str, Any]], Awaitable[Any]]


@dataclass(eq=False)
class Connection:
    device: Device
    socket: Socket
    tools: dict[str, DeviceTool]
    connected_at: float
    pending: dict[str, asyncio.Future[Any]] = field(default_factory=dict)
    closed: bool = False
    _send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, frame: dict[str, Any]) -> None:
        async with self._send_lock:
            await self.socket.send_text(encode(frame))

    def fail_pending(self, reason: str) -> None:
        for future in self.pending.values():
            if not future.done():
                future.set_exception(ToolError(reason))
        self.pending.clear()

    async def close(self, code: int, reason: str) -> None:
        if self.closed:
            return
        self.closed = True
        self.fail_pending(reason)
        with contextlib.suppress(Exception):
            await self.socket.close(code, reason)


CLOSE_GOING_AWAY = 1001  # the server is stopping: reconnect at once, to the next one


class DeviceHub:
    def __init__(
        self,
        devices: Devices,
        *,
        call_seconds: float = CALL_SECONDS,
        max_in_flight: int = MAX_IN_FLIGHT,
        event_seconds: float = EVENT_SECONDS,
        ping_seconds: float = PING_SECONDS,
        silence_seconds: float = SILENCE_SECONDS,
        hello_seconds: float = HELLO_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.devices = devices
        self.call_seconds = call_seconds
        self.max_in_flight = max_in_flight
        self.event_seconds = event_seconds
        self.ping_seconds = ping_seconds
        self.silence_seconds = silence_seconds
        self.hello_seconds = hello_seconds
        self.clock = clock
        self.connections: dict[int, Connection] = {}
        self.listeners: dict[int, set[asyncio.Queue[dict[str, Any]]]] = {}
        self.notifiers: list[Notifier] = []
        self._last_event: dict[int, float] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        # The welcome frame's extra fields for a user: their assistant's name, wake phrase.
        self.welcome_extra: Callable[[int], dict[str, Any]] = lambda user_id: {}
        # Where a device's observations go (learning), while its "routine" skill is on.
        self.observer: Observer | None = None

    # Connections.

    def connected(self, device_id: int) -> bool:
        return device_id in self.connections

    async def attach(self, connection: Connection) -> None:
        """Hold a new connection; one the same device had before is closed and its calls fail."""
        old = self.connections.get(connection.device.id)
        self.connections[connection.device.id] = connection
        if old is not None and old is not connection:
            await old.close(CLOSE_REPLACED, "replaced by a new connection from this device")

    def detach(self, connection: Connection) -> None:
        if self.connections.get(connection.device.id) is connection:
            del self.connections[connection.device.id]
        connection.fail_pending("the device disconnected")

    async def disconnect(self, device_id: int, reason: str = "revoked") -> bool:
        """Close a device's connection now (it was revoked). Its calls fail."""
        connection = self.connections.pop(device_id, None)
        if connection is None:
            return False
        await connection.close(CLOSE_REVOKED, reason)
        return True

    async def run(self, socket: Socket, device: Device) -> None:
        """Serve one accepted WebSocket for ``device`` until it closes."""
        try:
            text = await asyncio.wait_for(socket.receive_text(), self.hello_seconds)
            frame = decode(text)
            if frame.get("type") == "bye":
                # The device is being removed from its machine: it revokes its own token.
                self.devices.revoke(device.id)
                log.info("device %s said goodbye and was revoked", device.id)
                with contextlib.suppress(Exception):
                    await socket.close(1000, "goodbye")
                return
            hello = parse_hello(frame, device.kind)
        except TimeoutError:
            with contextlib.suppress(Exception):
                await socket.close(CLOSE_SILENT, "no hello")
            return
        except ProtocolError as exc:
            with contextlib.suppress(Exception):
                await socket.send_text(encode({"type": "error", "error": str(exc)}))
                await socket.close(CLOSE_BAD_HELLO, "bad hello")
            return
        except Exception:  # the device went away before saying hello
            return

        connection = Connection(
            device=device,
            socket=socket,
            tools={tool.name: tool for tool in hello.tools},
            connected_at=time.time(),
        )
        self.devices.hello(
            device.id, version=hello.version, tools=[tool.public() for tool in hello.tools]
        )
        await self.attach(connection)
        log.info("device %s connected with %d tools", device.id, len(hello.tools))
        pinger = asyncio.create_task(self._ping(connection))
        try:
            await connection.send(
                {
                    "type": "welcome",
                    "deviceId": device.id,
                    "label": device.label,
                    "skills": device.skills,
                    **self.welcome_extra(device.user_id),
                }
            )
            await self._serve(connection)
        except Exception as exc:  # a socket error ends the connection like a close does
            log.info("device %s connection ended: %s", device.id, type(exc).__name__)
        finally:
            pinger.cancel()
            self.detach(connection)
            self.devices.seen(device.id)
            log.info("device %s disconnected", device.id)

    async def _serve(self, connection: Connection) -> None:
        while not connection.closed:
            try:
                text = await asyncio.wait_for(
                    connection.socket.receive_text(), self.silence_seconds
                )
            except TimeoutError:
                await connection.close(CLOSE_SILENT, "nothing heard for 90 seconds")
                return
            if len(text) > MAX_FRAME_BYTES or len(text.encode()) > MAX_FRAME_BYTES:
                await connection.close(CLOSE_TOO_BIG, "frames are 1 MB at most")
                return
            try:
                frame = decode(text)
                await self._handle(connection, frame)
            except ProtocolError as exc:
                await connection.send({"type": "error", "error": str(exc)})

    async def _handle(self, connection: Connection, frame: dict[str, Any]) -> None:
        kind = frame["type"]
        if kind == "ping":
            await connection.send({"type": "pong"})
        elif kind == "pong":
            pass
        elif kind == "result":
            self._result(connection, frame)
        elif kind == "event":
            await self._event(connection, frame)
        elif kind == "observe":
            await self._observe(connection, frame)
        elif kind == "hello":
            raise ProtocolError("already said hello; reconnect to change the tools")
        else:
            raise ProtocolError(f"unknown frame type '{str(kind)[:40]}'")

    async def _ping(self, connection: Connection) -> None:
        while not connection.closed:
            await asyncio.sleep(self.ping_seconds)
            try:
                await connection.send({"type": "ping"})
            except Exception:
                return

    async def _observe(self, connection: Connection, frame: dict[str, Any]) -> None:
        device = self.devices.get(connection.device.id)
        if device is None or "routine" not in device.skills or self.observer is None:
            raise ProtocolError("the routine skill is off for this device; nothing was kept")
        try:
            await self.observer(device.user_id, device.id, frame)
        except ValueError as exc:  # LearningError: a frame learning refuses
            raise ProtocolError(str(exc)) from None

    async def push_skills(self, device_id: int, skills: list[str]) -> None:
        """Tell a connected device which skills are on now, so it starts or stops observing."""
        connection = self.connections.get(device_id)
        if connection is not None and not connection.closed:
            with contextlib.suppress(Exception):
                await connection.send({"type": "skills", "skills": skills})

    def push_skills_soon(self, device_id: int) -> None:
        """push_skills from code that cannot wait for it (a plain route)."""
        device = self.devices.get(device_id)
        if device is None:
            return
        with contextlib.suppress(RuntimeError):  # no running loop: nobody is connected
            task = asyncio.get_running_loop().create_task(
                self.push_skills(device_id, device.skills)
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    # Calls.

    async def call(
        self, device_id: int, tool: str, args: dict[str, Any], *, timeout: float | None = None
    ) -> Any:
        """Ask a device to run one of its tools; its content, or ToolError."""
        connection = self.connections.get(device_id)
        if connection is None or connection.closed:
            raise ToolError("the device is not connected")
        if tool not in connection.tools:
            raise ToolError(f"the device does not offer '{tool}'")
        if len(connection.pending) >= self.max_in_flight:
            raise ToolError(
                f"the device is busy: {self.max_in_flight} requests are already waiting"
            )
        call_id = str(uuid.uuid4())
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        connection.pending[call_id] = future
        seconds = self.call_seconds if timeout is None else timeout
        started = time.monotonic()
        try:
            await connection.send({"type": "call", "id": call_id, "tool": tool, "args": args})
            return await asyncio.wait_for(future, seconds)
        except TimeoutError:
            raise ToolError(f"the device did not answer within {seconds:g} seconds") from None
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"the device could not be reached ({type(exc).__name__})") from None
        finally:
            connection.pending.pop(call_id, None)
            log.info("device %s %s took %.2fs", device_id, tool, time.monotonic() - started)

    def _result(self, connection: Connection, frame: dict[str, Any]) -> None:
        future = connection.pending.get(str(frame.get("id")))
        if future is None or future.done():
            return  # late, after a timeout, or never asked
        if frame.get("ok") is True:
            future.set_result(frame.get("content"))
        else:
            error = clean_line(frame.get("error"), MAX_ERROR) or "the device reported an error"
            future.set_exception(ToolError(error))

    async def run_action(self, pending: PendingAction) -> Any:
        """Run a confirmed Tier 2 or 3 action on its device (the guard's device runner)."""
        assert pending.device_id is not None
        device = self.devices.get(pending.device_id)
        if device is None or device.user_id != pending.user_id:
            raise ToolError("that device is no longer paired")
        return await self.call(pending.device_id, pending.tool, pending.params)

    # Events.

    async def _event(self, connection: Connection, frame: dict[str, Any]) -> None:
        event = parse_event(frame)
        now = self.clock()
        last = self._last_event.get(connection.device.id)
        if last is not None and now - last < self.event_seconds:
            wait = round(self.event_seconds - (now - last))
            raise ProtocolError(f"one event per {self.event_seconds:g} seconds; wait {wait} s")
        self._last_event[connection.device.id] = now
        await self.publish(connection.device.user_id, connection.device.id, event)

    async def publish(self, user_id: int, device_id: int | None, event: Event) -> dict[str, Any]:
        """Keep an event and send it to its user's channels, and to nobody else's."""
        row = self.devices.add_event(user_id, device_id, event)
        for queue in list(self.listeners.get(user_id, ())):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(row)
        frame = {"type": "event", **{k: row[k] for k in ("event", "title", "text", "at")}}
        for connection in list(self.connections.values()):
            if connection.device.user_id == user_id and connection.device.kind == "android":
                with contextlib.suppress(Exception):
                    await connection.send(frame)
        for notify in self.notifiers:
            task = asyncio.create_task(self._notify(notify, user_id, row))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return row

    async def _notify(self, notify: Notifier, user_id: int, row: dict[str, Any]) -> None:
        try:
            await notify(user_id, row)
        except Exception:
            log.exception("an event notifier failed")

    def subscribe(self, user_id: int) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(LISTENER_QUEUE)
        self.listeners.setdefault(user_id, set()).add(queue)
        return queue

    def unsubscribe(self, user_id: int, queue: asyncio.Queue[dict[str, Any]]) -> None:
        queues = self.listeners.get(user_id)
        if queues is not None:
            queues.discard(queue)
            if not queues:
                del self.listeners[user_id]

    async def going_away(self, reason: str = "the server is restarting") -> None:
        """The server is stopping: close every device with 1001 (going away) so its app
        reconnects to the next server at once, and end every event stream."""
        for connection in list(self.connections.values()):
            await connection.close(CLOSE_GOING_AWAY, reason)
        for queues in list(self.listeners.values()):
            for queue in list(queues):
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(None)  # type: ignore[arg-type]  # the end of the stream

    # Tools.

    def tools_for(self, user_id: int | None) -> list[PersonalTool]:
        """This person's connected devices' tools whose skill they switched on."""
        if user_id is None:
            return []
        skills = {device.id: set(device.skills) for device in self.devices.for_user(user_id)}
        offered: dict[str, list[tuple[Connection, DeviceTool]]] = {}
        for connection in list(self.connections.values()):
            device = connection.device
            if device.user_id != user_id or connection.closed or device.id not in skills:
                continue
            for tool in connection.tools.values():
                if tool.skill in skills[device.id]:
                    offered.setdefault(tool.name, []).append((connection, tool))
        out = []
        for name, entries in offered.items():
            if len(entries) == 1:
                connection, tool = entries[0]
                out.append(self._single(connection, tool))
            elif "device" not in entries[0][1].parameters.get("properties", {}):
                out.append(self._shared(name, entries))
            else:  # the tool already takes "device": offer the newest connection's
                connection, tool = max(entries, key=lambda e: e[0].connected_at)
                out.append(self._single(connection, tool))
        return out

    def _single(self, connection: Connection, tool: DeviceTool) -> PersonalTool:
        device_id = connection.device.id

        async def run(arguments: dict[str, Any]) -> Any:
            return await self.call(device_id, tool.name, arguments)

        return PersonalTool(
            name=tool.name,
            description=f"{tool.description} (on {connection.device.label})",
            parameters=tool.parameters,
            tier=tool.tier,
            source="device",
            label=connection.device.label,
            run=run,
            device_id=device_id,
            skill=tool.skill,
        )

    def _shared(self, name: str, entries: list[tuple[Connection, DeviceTool]]) -> PersonalTool:
        """One tool that several of a person's devices offer: it gains a ``device`` argument."""
        by_label: dict[str, int] = {}
        for connection, _ in entries:
            label = connection.device.label
            if label in by_label:
                label = f"{label} (#{connection.device.id})"
            by_label[label] = connection.device.id
        first = entries[0][1]
        parameters = dict(first.parameters)
        properties = dict(parameters.get("properties", {}))
        properties["device"] = {
            "type": "string",
            "enum": list(by_label),
            "description": "Which of your devices to use.",
        }
        parameters["properties"] = properties
        parameters["required"] = [*parameters.get("required", []), "device"]

        def route(arguments: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            label = arguments.get("device")
            if label not in by_label:
                raise ToolError(f"device must be one of: {', '.join(by_label)}")
            rest = {k: v for k, v in arguments.items() if k != "device"}
            return by_label[label], rest

        async def run(arguments: dict[str, Any]) -> Any:
            device_id, rest = route(arguments)
            return await self.call(device_id, name, rest)

        return PersonalTool(
            name=name,
            description=first.description,
            parameters=parameters,
            tier=max(tool.tier for _, tool in entries),
            source="device",
            label="your devices",
            run=run,
            skill=first.skill,
            route=route,
        )
