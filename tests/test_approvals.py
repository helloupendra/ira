"""Approval windows: one PIN on screen control lets the next steps on that device run."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ira.approvals import covered
from ira.channels.http import create_app
from ira.devices.hub import Connection
from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider
from ira.tools.personal import PersonalTool

from .conftest import Clock, make_runtime

pytestmark = pytest.mark.anyio

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
PIN = "4321"


def test_what_a_window_covers():
    assert covered("screen_act", "screen") and covered("screen_read", "screen")
    assert covered("mac_click", "control") and covered("app_open", "apps")
    assert covered("url_open", "apps") and covered("media_play", "media")
    for never in ("sms_send", "call_place", "notification_reply", "messages_send", "mail_send"):
        assert not covered(never, "screen"), never
    assert not covered("screen_send", "screen")  # its name says it sends
    assert not covered("calendar_add", "calendar")


class Socket:
    async def send_text(self, data: str) -> None:
        pass

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        pass


TOOLS = [
    {"name": "screen_act", "skill": "screen", "tier": 3},
    {"name": "sms_send", "skill": "messages", "tier": 2},
]


def phone_world(script: list[Any]):
    provider = ScriptedProvider(script)
    runtime = make_runtime(provider=provider)
    clock = Clock()
    runtime.approvals.clock = clock
    owner = runtime.accounts.create_user("owner@example.com", PASSWORD, "owner")
    runtime.guard.set_pin(PIN, user_id=owner.id, actor=owner.email, channel="test")
    devices = runtime.hub.devices
    code, _ = devices.start_pairing(owner.id, "android", "Pixel 7", ["screen", "messages"])
    token, phone = devices.redeem(code)
    devices.hello(phone.id, version="1", tools=TOOLS)
    runtime.hub.connections[phone.id] = Connection(phone, Socket(), {}, 0.0)
    ran: list[str] = []

    def tool(spec: dict[str, Any]) -> PersonalTool:
        async def run(arguments: dict[str, Any]) -> Any:
            ran.append(spec["name"])
            return {"done": True, "summary": f"{spec['name']} done"}

        return PersonalTool(
            spec["name"],
            spec["name"],
            {"type": "object", "properties": {}},
            spec["tier"],
            source="device",
            label="Pixel 7",
            run=run,
            device_id=phone.id,
            skill=spec["skill"],
        )

    runtime.assistant.personal_tools = lambda uid: (
        [tool(t) for t in TOOLS] if uid == owner.id else []
    )

    async def on_device(pending):
        ran.append(pending.tool)
        return {"done": True}

    runtime.guard.device_runner = on_device
    return runtime, provider, owner, phone, token, ran, clock


def act(name: str) -> ChatResponse:
    return ChatResponse(text="", tool_calls=[ToolCall("c1", name, json.dumps({}))])


async def test_a_pin_opens_a_window_and_covered_steps_then_run():
    runtime, provider, owner, phone, _, ran, clock = phone_world(
        [
            act("screen_act"),
            "Tap Search? Your PIN.",
            "Done.",
            act("screen_act"),
            "Tapped.",
            act("sms_send"),
            "Send it?",
            act("screen_act"),
            "PIN please.",
        ]  # fmt: skip
    )
    ask = runtime.assistant.ask
    first = await ask("YouTube pe search tap karo", conversation_id="t", user_id=owner.id)
    assert first.action is not None and ran == []
    outcome = await runtime.guard.confirm(first.action.id, PIN, user_id=owner.id, role="owner")
    assert outcome.status == "executed" and ran == ["screen_act"]
    [window] = runtime.approvals.for_user(owner.id)
    assert (window.device_id, round(window.expires_at - clock())) == (phone.id, 15 * 60)

    # The next screen step runs at once, says so, and the model was told the window is open.
    [e async for e in runtime.assistant.follow_up("t", channel="api", actor="o", user_id=owner.id)]
    second = await ask("ab type karo news", conversation_id="t", user_id=owner.id)
    assert second.action is None and ran == ["screen_act", "screen_act"]
    assert "approved screen and app control" in provider.calls[3]["messages"][0].text
    log = runtime.store.one("SELECT outcome, tier FROM tool_log ORDER BY id DESC LIMIT 1")
    assert (log["outcome"], log["tier"]) == ("approved", 3)
    assert runtime.approvals.for_user(owner.id)[0].steps == 1

    # Sending is never covered: it still waits for a yes.
    third = await ask("Rahul ko SMS karo", conversation_id="t", user_id=owner.id)
    assert third.action is not None and third.action.tool == "sms_send"
    assert ran == ["screen_act", "screen_act"]

    # Its time runs out: the next screen step asks again.
    clock.advance(15 * 60 + 1)
    fourth = await ask("aur scroll karo", conversation_id="u", user_id=owner.id)
    assert fourth.action is not None and fourth.action.tool == "screen_act"


async def test_stop_disconnect_and_minutes():
    runtime, _, owner, phone, token, _, clock = phone_world([])
    runtime.approvals.open(owner.id, phone.id)
    assert runtime.approvals.covers(owner.id, phone.id, "screen_act", "screen") is not None
    del runtime.hub.connections[phone.id]  # the phone went away: so does its window
    assert runtime.approvals.covers(owner.id, phone.id, "screen_act", "screen") is None

    runtime.hub.connections[phone.id] = Connection(phone, Socket(), {}, 0.0)
    runtime.approvals.open(owner.id, phone.id)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        body = {"email": "owner@example.com", "password": PASSWORD, "use_cookie": False}
        session = client.post("/v1/auth/login", json=body).json()["session_token"]
        me = {"Authorization": f"Bearer {session}"}
        device = {"Authorization": f"Bearer {token}"}
        view = client.get("/v1/me/approvals", headers=device).json()
        assert view["minutes"] == 15 and view["windows"][0]["device"] == "Pixel 7 (Android)"
        window_id = view["windows"][0]["id"]
        assert client.delete(f"/v1/me/approvals/{window_id}", headers=device).json() == {
            "ok": True
        }  # the phone itself may stop it
        assert client.get("/v1/me/approvals", headers=me).json()["windows"] == []

        # A device cannot change how long approvals last; raising it needs the PIN.
        assert client.put(
            "/v1/me/approvals/minutes", json={"minutes": 60}, headers=device
        ).status_code in (401, 403)
        assert (
            client.put("/v1/me/approvals/minutes", json={"minutes": 60}, headers=me).status_code
            == 403
        )
        raised = client.put(
            "/v1/me/approvals/minutes", json={"minutes": 30, "pin": PIN}, headers=me
        ).json()
        assert raised["minutes"] == 30
        assert (
            client.put("/v1/me/approvals/minutes", json={"minutes": 7}, headers=me).json()[
                "minutes"
            ]
            == 7
        )  # lowering needs no PIN
        assert (
            client.put("/v1/me/approvals/minutes", json={"minutes": 3}, headers=me).status_code
            == 422
        )
        runtime.approvals.open(owner.id, phone.id)
        off = client.put("/v1/me/approvals/minutes", json={"minutes": 0}, headers=me).json()
        assert off == {"minutes": 0, "windows": []}
    assert runtime.approvals.open(owner.id, phone.id) is None  # off: a PIN opens nothing
