"""The read-only admin API that the v0.2 console will call."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"


@pytest.fixture
def setup(registry):
    provider = ScriptedProvider(
        [
            ChatResponse(
                text="", tool_calls=[ToolCall("c1", "order_status", '{"order_id": "A1"}')]
            ),
            "It shipped.",
            ChatResponse(
                text="", tool_calls=[ToolCall("c2", "refund", '{"order_id": "A1", "amount": 5}')]
            ),
            "Proposed.",
        ]
    )
    runtime = make_runtime(provider=provider, registry=registry)
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    session, _ = runtime.accounts.start_session(owner)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        headers = {"Authorization": f"Bearer {session}"}
        client.post(
            "/v1/ask", json={"text": "where is A1", "conversation_id": "c1"}, headers=headers
        )
        client.post("/v1/ask", json={"text": "refund A1", "conversation_id": "c1"}, headers=headers)
        yield client, headers, runtime


def test_overview_counts_today(setup):
    client, headers, runtime = setup
    data = client.get("/v1/admin/overview", headers=headers).json()
    # Two questions, each answered with a tool round: four model calls.
    assert data["questions"] == 2
    assert data["calls"] == 4
    assert data["failures"] == 0
    assert data["actions"] == {"pending": 1}
    assert data["conversations"] == 1
    assert data["by_model"][0]["model"] == "fake:m"
    assert data["latency_p50"] is not None

    # Questions are counted from today's stored user messages, on any channel.
    runtime.store.execute("UPDATE messages SET at = at - 86400 WHERE content = 'where is A1'")
    assert client.get("/v1/admin/overview", headers=headers).json()["questions"] == 1


def test_calls_conversations_and_transcript(setup):
    client, headers, _ = setup
    calls = client.get("/v1/admin/calls?limit=2", headers=headers).json()
    assert len(calls) == 2 and calls[0]["id"] > calls[1]["id"]
    older = client.get(f"/v1/admin/calls?before_id={calls[1]['id']}", headers=headers).json()
    assert all(c["id"] < calls[1]["id"] for c in older)

    conversations = client.get("/v1/admin/conversations", headers=headers).json()
    assert conversations[0]["turns"] == 2 and conversations[0]["email"] == "owner@example.com"
    assert conversations[0]["preview"] == "where is A1"
    transcript = client.get(f"/v1/admin/conversations/{conversations[0]['id']}", headers=headers)
    roles = [m["role"] for m in transcript.json()]
    assert roles.count("tool") == 2
    calls = [c for m in transcript.json() for c in m["tool_calls"]]
    assert calls[0] == {"id": "c1", "name": "order_status", "arguments": '{"order_id": "A1"}'}
    assert client.get("/v1/admin/conversations/nope", headers=headers).status_code == 404


def test_actions_audit_tools_channels_users_tokens(setup):
    client, headers, runtime = setup
    actions = client.get("/v1/admin/actions?status=pending", headers=headers).json()
    assert actions[0]["params"] == {"order_id": "A1", "amount": 5}

    audit = client.get("/v1/admin/audit", headers=headers).json()
    assert audit[0]["outcome"] == "proposed"

    tools = {t["name"]: t for t in client.get("/v1/admin/tools", headers=headers).json()}
    assert tools["refund"]["kind"] == "action"
    assert "order_id" in tools["refund"]["parameters"]["properties"]

    channels = {c["name"]: c for c in client.get("/v1/admin/channels", headers=headers).json()}
    assert channels["telegram"]["enabled"] is False
    assert channels["telegram"]["detail"]["paired_chats"] == 0

    users = client.get("/v1/admin/users", headers=headers).json()
    assert users[0]["email"] == "owner@example.com"
    assert "password_hash" not in users[0]

    runtime.accounts.create_token(runtime.accounts.users()[0], "phone", ["ask"])
    tokens = client.get("/v1/admin/tokens", headers=headers).json()
    assert tokens[0]["label"] == "phone" and "token_hash" not in tokens[0]


def test_one_conversation_header_and_its_declared_404(setup):
    client, headers, _ = setup
    listed = client.get("/v1/admin/conversations", headers=headers).json()[0]
    info = client.get(f"/v1/admin/conversations/{listed['id']}/info", headers=headers)
    assert info.status_code == 200 and info.json() == listed
    assert info.json()["email"] == "owner@example.com" and info.json()["turns"] == 2
    missing = client.get("/v1/admin/conversations/nope/info", headers=headers)
    assert missing.status_code == 404 and missing.json() == {"detail": "no such conversation"}

    paths = client.get("/v1/openapi.json").json()["paths"]
    for path in (
        "/v1/admin/conversations/{conversation_id}",
        "/v1/admin/conversations/{conversation_id}/info",
        "/v1/conversations/{conversation_id}",
    ):
        not_found = paths[path]["get"]["responses"]["404"]
        assert "ErrorDetail" in str(not_found), path


def test_calls_list_the_models_tried_and_tools_say_their_kind(setup):
    client, headers, runtime = setup
    runtime.store.execute(
        "INSERT INTO calls (at, tier, purpose, model, tried, attempts, ok, seconds) "
        "VALUES (1, 'default', 'chat', 'b:m', 'a:m,b:m', 2, 1, 0.1)"
    )
    newest = client.get("/v1/admin/calls?limit=1", headers=headers).json()[0]
    assert newest["tried"] == "a:m,b:m" and newest["tried_list"] == ["a:m", "b:m"]

    schema = client.get("/v1/openapi.json").json()["components"]["schemas"]
    assert schema["ToolDetail"]["properties"]["kind"]["enum"] == ["read", "action"]
    assert "tried_list" in schema["CallRow"]["properties"]


def test_the_overview_says_when_its_day_starts_and_where(setup):
    import datetime as dt

    client, headers, _ = setup
    data = client.get("/v1/admin/overview", headers=headers).json()
    start = dt.datetime.fromisoformat(data["since_iso"])
    assert start.timestamp() == data["since"]
    assert (start.hour, start.minute, start.second) == (0, 0, 0)
    assert start.utcoffset() == dt.datetime.now().astimezone().utcoffset()
    assert data["timezone"]


def test_the_time_zone_is_a_name_when_known_else_an_offset(monkeypatch):
    import re

    from ira.channels import admin

    monkeypatch.setenv("TZ", "Asia/Kolkata")
    assert admin.local_timezone() == "Asia/Kolkata"
    monkeypatch.setenv("TZ", ":Europe/London")
    assert admin.local_timezone() == "Europe/London"

    monkeypatch.setenv("TZ", "IST-5:30")  # a POSIX rule, not a name
    monkeypatch.setattr(admin.os, "readlink", lambda path: "/usr/share/zoneinfo/America/Chicago")
    assert admin.local_timezone() == "America/Chicago"

    def nowhere(*args, **kwargs):
        raise OSError("not here")

    monkeypatch.setattr(admin.os, "readlink", nowhere)
    monkeypatch.setattr(admin, "Path", lambda path: type("P", (), {"read_text": nowhere})())
    assert re.fullmatch(r"[+-]\d\d:\d\d", admin.local_timezone())
