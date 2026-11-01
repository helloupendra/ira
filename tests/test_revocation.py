"""Revoking a device, signing out or removing a person ends what is already open:
a live voice call, the events stream, and a device socket that has not said hello yet."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ira.channels.deps import device_principal
from ira.channels.devices import my_event_stream
from ira.channels.http import create_app
from ira.channels.live import CLOSE_UNAUTHORIZED, SIGNED_OUT
from ira.devices import DeviceHub, Devices
from ira.devices.protocol import CLOSE_REVOKED
from ira.models.fake import ScriptedProvider
from ira.store import Store
from ira.voice.providers import FakeSTT, FakeTTS
from tests.conftest import make_runtime
from tests.test_devices import FakeSocket, hello, paired, person

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret


def _staff_phone(runtime: Any) -> tuple[Any, str, Any]:
    runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    staff = runtime.accounts.create_user("staff@example.com", PASSWORD, "staff")
    code, _ = runtime.hub.devices.start_pairing(staff.id, "android", "Phone", [])
    token, device = runtime.hub.devices.redeem(code)
    return staff, token, device


def _until(ws: Any, kind: str) -> list[dict[str, Any]]:
    seen = []
    while True:
        message = ws.receive_json()
        if message["type"] == "audio":
            ws.receive_bytes()
        seen.append(message)
        if message["type"] == kind:
            return seen


def test_revoking_a_device_hangs_up_its_live_call():
    runtime = make_runtime(
        provider=ScriptedProvider(["First answer.", "Never said."]),
        stt=FakeSTT("hello"),
        tts=FakeTTS(),
    )
    _, token, device = _staff_phone(runtime)
    client = TestClient(create_app(runtime, start_channels=False))
    with (
        client,
        client.websocket_connect(
            "/v1/voice/live", headers={"Authorization": f"Bearer {token}"}
        ) as ws,
    ):
        ws.send_json({"type": "start", "protocol": 1, "conversation_id": "c1"})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "text", "text": "first"})
        assert _until(ws, "done")[-1]["text"] == "First answer."

        assert runtime.hub.devices.revoke(device.id)
        ws.send_json({"type": "text", "text": "second"})
        error = ws.receive_json()
        assert error == {"type": "error", "message": SIGNED_OUT, "fatal": True}
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == CLOSE_UNAUTHORIZED


def test_removing_a_person_hangs_up_their_signed_in_call():
    runtime = make_runtime(
        provider=ScriptedProvider(["First answer.", "Never said."]),
        stt=FakeSTT("hello"),
        tts=FakeTTS(),
    )
    staff, _, _ = _staff_phone(runtime)
    client = TestClient(create_app(runtime, start_channels=False))
    with client:
        signed_in = client.post(
            "/v1/auth/login",
            json={"email": "staff@example.com", "password": PASSWORD},
            headers={"X-Ira-Request": "1"},
        )
        assert signed_in.status_code == 200
        with client.websocket_connect("/v1/voice/live") as ws:
            ws.send_json({"type": "start", "protocol": 1, "conversation_id": "c1"})
            assert ws.receive_json()["type"] == "ready"
            runtime.accounts.remove_user(staff.id)
            ws.send_json({"type": "text", "text": "anything"})
            assert ws.receive_json()["message"] == SIGNED_OUT


class _StreamRequest:
    def __init__(self, token: str) -> None:
        self.headers = {"authorization": f"Bearer {token}"}
        self.cookies: dict[str, str] = {}

    async def is_disconnected(self) -> bool:
        return False


@pytest.mark.anyio
async def test_revoking_a_device_ends_its_events_stream_before_the_next_frame(tmp_path):
    runtime = make_runtime(data_dir=tmp_path)
    staff, token, device = _staff_phone(runtime)
    who = device_principal(runtime, token)
    assert who is not None and who.can("drop")
    response = await my_event_stream(_StreamRequest(token), who, runtime)
    body = response.body_iterator
    assert (await body.__anext__()).startswith(": connected")

    before = runtime.drop.add_text(staff.id, "a note before", from_label="Web")
    await runtime.drop_changed(staff.id, {"type": "drop", "event": "new", "item": before.public()})
    assert "a note before" in await asyncio.wait_for(body.__anext__(), 2)

    runtime.hub.devices.revoke(device.id)
    after = runtime.drop.add_text(staff.id, "a note after", from_label="Web")
    await runtime.drop_changed(staff.id, {"type": "drop", "event": "new", "item": after.public()})
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(body.__anext__(), 2)


@pytest.mark.anyio
async def test_a_device_revoked_before_its_hello_never_attaches():
    store = Store(":memory:")
    devices = Devices(store)
    hub = DeviceHub(devices)
    owner = person(store)
    token, device = paired(devices, owner.id, kind="android", skills=())
    socket = FakeSocket()
    task = asyncio.create_task(hub.run(socket, device))
    await asyncio.sleep(0.05)
    # The token was checked when the socket opened; it is revoked while hello is awaited.
    assert devices.revoke(device.id)
    assert await hub.disconnect(device.id) is False
    socket.say(hello("android", tools=[]))
    await asyncio.wait_for(task, 2)
    assert socket.closed is not None and socket.closed[0] == CLOSE_REVOKED
    assert not hub.connected(device.id)
    assert await hub.send_to_person(owner.id, {"type": "drop", "event": "new"}) == 0
    assert socket.sent.empty()
    assert devices.by_token(token) is None


@pytest.mark.anyio
async def test_a_connected_device_revoked_without_a_hang_up_gets_no_frames_and_says_nothing():
    store = Store(":memory:")
    devices = Devices(store)
    hub = DeviceHub(devices)
    owner = person(store)
    _, device = paired(devices, owner.id, kind="android", skills=())
    socket = FakeSocket()
    task = asyncio.create_task(hub.run(socket, device))
    socket.say(hello("android", tools=[]))
    assert (await socket.next())["type"] == "welcome"
    assert hub.connected(device.id)

    devices.revoke(device.id)  # the database says so; nobody told the hub
    socket.say({"type": "event", "event": "task_done", "title": "Injected", "text": "hi"})
    await asyncio.sleep(0.05)
    assert devices.events(owner.id) == []
    assert await hub.send_to_person(owner.id, {"type": "drop", "event": "new"}) == 0
    assert not hub.connected(device.id)
    task.cancel()
