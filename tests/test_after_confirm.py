"""After an action is confirmed, Ira sees what it did and carries on: never "pending" again."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider
from ira.tools.registry import ToolError
from ira.voice.providers import FakeSTT, FakeTTS

from .conftest import make_runtime

pytestmark = pytest.mark.anyio

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
PIN = "4321"


def call(name: str, arguments: str) -> ChatResponse:
    return ChatResponse(text="", tool_calls=[ToolCall("c1", name, arguments)])


def signed_in(client):
    body = {"email": "owner@example.com", "password": PASSWORD, "use_cookie": False}
    token = client.post("/v1/auth/login", json=body).json()["session_token"]
    return {"Authorization": f"Bearer {token}"}


def setup(provider, registry, **kwargs):
    runtime = make_runtime(provider=provider, registry=registry, **kwargs)
    me = runtime.accounts.create_user("owner@example.com", PASSWORD, "owner")
    runtime.guard.set_pin(PIN, user_id=me.id, actor=me.email, channel="test")
    return runtime


def test_a_pin_on_the_card_runs_it_and_ira_answers_with_the_result(registry, ledger):
    provider = ScriptedProvider(
        [
            call("refund", '{"order_id": "A1", "amount": 5}'),
            "Refund 5 on A1: confirm with your PIN.",
            "Refund ho gaya: 5 on A1.",
            "Haan, A1 ka refund ho chuka hai.",
        ]
    )
    runtime = setup(provider, registry)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        me = signed_in(client)
        asked = client.post("/v1/ask", json={"text": "A1 ka 5 refund karo"}, headers=me).json()
        action = asked["action"]
        assert action and ledger.refunds == []

        path = f"/v1/actions/{action['id']}/confirm"
        done = client.post(path, json={"pin": PIN}, headers=me).json()
        assert done["status"] == "executed" and ledger.refunds == [("A1", 5)]
        assert done["reply"] == "Refund ho gaya: 5 on A1." and done["reply_message_id"]
        result = next(m for m in provider.calls[2]["messages"] if m.role == "tool")
        assert '"status": "done"' in result.text and '"refunded": 5' in result.text
        assert provider.calls[2]["messages"][-1].text.startswith("(I confirmed it.")

        # The next turn sees the action done, never "pending_confirmation" again.
        conversation = asked["conversation_id"]
        body = {"text": "ho gaya?", "conversation_id": conversation}
        again = client.post("/v1/ask", json=body, headers=me).json()
        assert again["text"] == "Haan, A1 ka refund ho chuka hai."
        sent = provider.calls[3]["messages"]
        assert not any("pending_confirmation" in (m.text or "") for m in sent)
        # The cue was said to the model, never stored.
        stored = [r["content"] for r in runtime.store.query("SELECT content FROM messages")]
        assert not any("(I confirmed it." in (c or "") for c in stored)


async def test_a_failed_action_is_told_to_the_model(registry):
    @registry.action(summary="Close {order_id}", tier=2)
    def close_order(order_id: str) -> dict:
        """Close an order."""
        raise ToolError("nothing on the screen says 'Search'")

    provider = ScriptedProvider(
        [
            call("close_order", '{"order_id": "A1"}'),
            "Close A1?",
            "Close nahi hua: Search nahi mila.",
        ]
    )
    runtime = setup(provider, registry)
    me = runtime.accounts.find_user("owner@example.com")
    await runtime.assistant.ask("A1 band karo", conversation_id="t", user_id=me.id)
    reply = await runtime.assistant.ask("haan", conversation_id="t", user_id=me.id)
    assert reply.text == "Close nahi hua: Search nahi mila."
    result = next(m for m in provider.calls[-1]["messages"] if m.role == "tool")
    assert '"status": "failed"' in result.text and "Search" in result.text


def test_in_a_live_call_the_answer_is_spoken_there(registry, ledger):
    provider = ScriptedProvider(
        [
            call("refund", '{"order_id": "A1", "amount": 5}'),
            "Refund 5 on A1. Type your PIN in the app.",
            "Refund ho gaya.",
        ]
    )
    runtime = setup(provider, registry, stt=FakeSTT("A1 ka refund karo"), tts=FakeTTS())
    with TestClient(create_app(runtime, start_channels=False)) as client:
        me = signed_in(client)
        with client.websocket_connect("/v1/voice/live", headers=me) as ws:
            ws.send_json({"type": "start", "protocol": 1, "conversation_id": "c9"})
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "text", "text": "A1 ka 5 refund karo"})
            seen = []
            while not seen or seen[-1]["type"] != "done":
                message = ws.receive_json()
                if message["type"] == "audio":
                    ws.receive_bytes()
                seen.append(message)
            action = next(m["action"] for m in seen if m["type"] == "action")
            assert "http:1:c9" in runtime.live_calls

            done = client.post(
                f"/v1/actions/{action['id']}/confirm", json={"pin": PIN}, headers=me
            ).json()
            assert done["status"] == "executed" and done["continued_in_call"] is True
            assert done["reply"] is None
            spoken = []
            while True:
                message = ws.receive_json()
                if message["type"] == "audio":
                    ws.receive_bytes()
                    spoken.append(message["text"])
                if message["type"] == "done":
                    break
            assert message["text"] == "Refund ho gaya." and spoken == ["Refund ho gaya."]
            ws.send_json({"type": "bye"})
    assert ledger.refunds == [("A1", 5)]
    assert runtime.live_calls == {}
