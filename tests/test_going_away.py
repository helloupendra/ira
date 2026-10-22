"""Stopping the server: devices, calls and event streams are told to go, so a restart is quick."""

from __future__ import annotations

import asyncio
import signal

import pytest

from ira.cli import GRACEFUL_SECONDS, going_away_server
from ira.devices.hub import CLOSE_GOING_AWAY

from .conftest import make_runtime

pytestmark = pytest.mark.anyio


class Socket:
    def __init__(self) -> None:
        self.closed: list = []

    async def receive_text(self) -> str:
        await asyncio.sleep(3600)
        return ""

    async def send_text(self, data: str) -> None:
        pass

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed.append(code)


class Call:
    def __init__(self) -> None:
        self.hung_up = 0

    async def hang_up(self) -> None:
        self.hung_up += 1


async def test_devices_calls_and_streams_are_told_to_go():
    runtime = make_runtime()
    owner = runtime.accounts.create_user("owner@example.com", "a-long-password-here", "owner")
    devices = runtime.hub.devices
    code, _ = devices.start_pairing(owner.id, "android", "Pixel 7", [])
    _, phone = devices.redeem(code)
    from ira.devices.hub import Connection

    socket = Socket()
    runtime.hub.connections[phone.id] = Connection(phone, socket, {}, 0.0)
    stream = runtime.hub.subscribe(owner.id)
    call = Call()
    runtime.live_calls["http:1:c1"] = call

    await runtime.going_away()

    assert socket.closed == [CLOSE_GOING_AWAY] == [1001]
    assert await asyncio.wait_for(stream.get(), 1) is None  # the stream ends
    assert call.hung_up == 1


async def test_the_server_tells_them_the_moment_it_is_asked_to_stop():
    import uvicorn

    told: list = []

    class Runtime:
        async def going_away(self) -> None:
            told.append("going")

    config = uvicorn.Config(lambda scope, receive, send: None, timeout_graceful_shutdown=5)
    server = going_away_server(config, Runtime())
    server.handle_exit(signal.SIGTERM, None)
    server.handle_exit(signal.SIGTERM, None)  # a second signal does not tell them twice
    await asyncio.sleep(0)
    assert told == ["going"] and server.should_exit
    assert config.timeout_graceful_shutdown == GRACEFUL_SECONDS == 5


def test_a_hang_up_is_an_ending_not_a_failure():
    from starlette.websockets import WebSocketDisconnect

    from ira.voice.live import hung_up

    class ClientDisconnected(OSError):  # uvicorn's, by name
        pass

    assert hung_up(ClientDisconnected()) and hung_up(WebSocketDisconnect(1001))
    try:
        try:
            raise ClientDisconnected()
        except OSError as inner:
            raise RuntimeError("sending failed") from inner
    except RuntimeError as outer:
        assert hung_up(outer)
    assert not hung_up(ValueError("a real bug"))
