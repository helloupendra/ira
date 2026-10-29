"""Only the person who asked answers a personal action; an ask-only key never says yes."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider
from ira.tools.personal import PersonalTool

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
PIN = "4321"


def call(name: str, arguments: dict) -> ChatResponse:
    return ChatResponse(text="", tool_calls=[ToolCall("c1", name, json.dumps(arguments))])


def login(client, email):
    body = {"email": email, "password": PASSWORD, "use_cookie": False}
    token = client.post("/v1/auth/login", json=body).json()["session_token"]
    return {"Authorization": f"Bearer {token}"}


def world(script: list[Any], registry):
    provider = ScriptedProvider(script)
    runtime = make_runtime(provider=provider, registry=registry)
    alice = runtime.accounts.create_first_owner("alice@example.com", PASSWORD)
    bob = runtime.accounts.create_user("bob@example.com", PASSWORD, "admin")
    for person in (alice, bob):
        runtime.guard.set_pin(PIN, user_id=person.id)
    ran: list[str] = []

    async def mail(arguments: dict[str, Any]) -> Any:
        ran.append("mail_send")
        return {"sent": True}

    mac = PersonalTool(
        "mail_send",
        "Send a mail from the Mac",
        {"type": "object", "properties": {"to": {"type": "string"}}},
        3,
        source="device",
        label="Alice's Mac",
        run=mail,
        device_id=9,
        skill="mail",
    )
    runtime.assistant.personal_tools = lambda uid: [mac] if uid == alice.id else []

    async def on_device(pending):
        ran.append(pending.tool)
        return {"sent": True}

    runtime.guard.device_runner = on_device
    return runtime, alice, bob, ran


def test_only_the_asker_confirms_or_cancels_a_personal_action(registry, ledger):
    runtime, alice, bob, ran = world(
        [call("mail_send", {"to": "ca@example.com"}), "Send it? Your PIN.", "Sent.",
         call("refund", {"order_id": "A1", "amount": 5}), "Refund? PIN.", "Done."],
        registry,
    )  # fmt: skip
    with TestClient(create_app(runtime, start_channels=False)) as client:
        her, him = login(client, "alice@example.com"), login(client, "bob@example.com")
        action = client.post("/v1/ask", json={"text": "mail the CA"}, headers=her).json()["action"]
        path = f"/v1/actions/{action['id']}"
        refused = client.post(f"{path}/confirm", json={"pin": PIN}, headers=him)
        assert refused.status_code == 403 and refused.json()["status"] == "not_allowed"
        assert client.post(f"{path}/cancel", headers=him).json()["status"] == "not_allowed"
        assert runtime.guard.wrong_pins(bob.id) == 0 and ran == []  # no PIN attempt used
        done = client.post(f"{path}/confirm", json={"pin": PIN}, headers=her).json()
        assert done["status"] == "executed" and ran == ["mail_send"]

        # A business's own action: anyone allowed to confirm it still may.
        action = client.post("/v1/ask", json={"text": "refund A1"}, headers=her).json()["action"]
        done = client.post(f"/v1/actions/{action['id']}/confirm", json={"pin": PIN}, headers=him)
        assert done.json()["status"] == "executed" and ledger.refunds == [("A1", 5)]


def test_an_ask_only_key_cannot_say_yes(registry):
    @registry.action(summary="Send the invoice for {order_id}", tier=2)
    def send_invoice(order_id: str) -> dict:
        """Send an invoice."""
        return {"sent": order_id}

    provider = ScriptedProvider(
        [
            call("send_invoice", {"order_id": "A1"}),
            "Send it?",
            call("send_invoice", {"order_id": "A2"}),
            "Send it?",
        ]
    )
    runtime = make_runtime(provider=provider, registry=registry)
    alice = runtime.accounts.create_first_owner("alice@example.com", PASSWORD)
    runtime.guard.set_pin(PIN, user_id=alice.id)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        her = login(client, "alice@example.com")
        made = client.post("/v1/me/tokens", json={"pin": PIN}, headers=her).json()
        siri = {"Authorization": f"Bearer {made['token']}"}
        asked = client.post("/v1/ask", json={"text": "invoice A1 bhejo"}, headers=siri).json()
        action, conversation = asked["action"], asked["conversation_id"]
        assert client.post(f"/v1/actions/{action['id']}/approve", headers=siri).status_code == 403
        said = client.post(
            "/v1/ask", json={"text": "haan", "conversation_id": conversation}, headers=siri
        ).json()
        assert "can only ask" in said["text"]
        assert runtime.guard.get(action["id"]).status == "pending"
        # Saying no is always allowed.
        no = client.post(
            "/v1/ask", json={"text": "nahi", "conversation_id": conversation}, headers=siri
        ).json()
        assert no["text"].startswith("Cancelled")
