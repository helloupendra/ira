"""Each assistant message keeps the model that wrote it."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.models.base import ChatResponse, ProviderError, ToolCall
from ira.models.fake import ScriptedProvider
from ira.models.gateway import Gateway
from ira.store import Store

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret


def test_each_assistant_message_names_its_model_even_after_a_fallback(registry):
    lookup = ChatResponse(
        text="", tool_calls=[ToolCall("c1", "order_status", '{"order_id": "A1"}')]
    )
    first = ScriptedProvider([lookup, ProviderError("busy", kind="capacity")])
    second = ScriptedProvider(["It shipped."])
    runtime = make_runtime(registry=registry)
    runtime.assistant.gateway = runtime.gateway = Gateway(
        {"a": first, "b": second}, {"default": ["a:m", "b:m"]}, store=runtime.store
    )
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    session, _ = runtime.accounts.start_session(owner)
    headers = {"Authorization": f"Bearer {session}"}
    with TestClient(create_app(runtime, start_channels=False)) as client:
        client.post(
            "/v1/ask", json={"text": "where is A1", "conversation_id": "k"}, headers=headers
        )
        messages = client.get("/v1/conversations/k", headers=headers).json()

    assert [(m["role"], m["model"]) for m in messages] == [
        ("user", None),
        ("assistant", "a:m"),  # the tool round
        ("tool", None),
        ("assistant", "b:m"),  # the answer, after a:m fell over
    ]


def test_no_model_is_named_when_none_answered(registry):
    failing = ScriptedProvider([ProviderError("down", kind="server")])
    runtime = make_runtime(provider=failing, registry=registry)
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    session, _ = runtime.accounts.start_session(owner)
    headers = {"Authorization": f"Bearer {session}"}
    with TestClient(create_app(runtime, start_channels=False)) as client:
        client.post("/v1/ask", json={"text": "hello", "conversation_id": "k"}, headers=headers)
        messages = client.get("/v1/admin/conversations/http:1:k", headers=headers).json()
    assert messages[-1]["role"] == "assistant" and messages[-1]["model"] is None


def test_older_messages_have_no_model(tmp_path):
    path = tmp_path / "old.db"
    store = Store(path)
    store.execute("ALTER TABLE messages DROP COLUMN model")  # as stored before this field
    store.execute(
        "INSERT INTO conversations (id, channel, started_at, last_at) VALUES ('c', 'web', 1, 1)"
    )
    store.execute(
        "INSERT INTO messages (conversation_id, at, role, content) "
        "VALUES ('c', 1, 'assistant', 'hi')"
    )
    store.close()

    from ira.conversations import Conversations

    (message,) = Conversations(Store(path)).transcript("c")
    assert message["model"] is None and message["content"] == "hi"
