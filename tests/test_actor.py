"""actor names the person; channel says where. Older "x via web" rows are cleaned on read."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ira import changes
from ira.channels.http import create_app
from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
REFUND = ChatResponse(
    text="", tool_calls=[ToolCall("c", "refund", '{"order_id": "A1", "amount": 5}')]
)


@pytest.fixture
def world(registry):
    runtime = make_runtime(provider=ScriptedProvider([REFUND, "ok"]), registry=registry)
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    session, _ = runtime.accounts.start_session(owner)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        yield client, {"Authorization": f"Bearer {session}"}, runtime


def test_new_rows_store_the_person_and_the_channel_apart(world):
    client, headers, runtime = world
    action = client.post("/v1/ask", json={"text": "refund A1"}, headers=headers).json()["action"]
    client.post(f"/v1/actions/{action['id']}/cancel", headers=headers)
    client.patch("/v1/admin/settings", json={"name": "Sunny"}, headers=headers)

    stored = runtime.store.one("SELECT actor, channel FROM pending_actions")
    assert (stored["actor"], stored["channel"]) == ("owner@example.com", "web")
    audit = runtime.store.query("SELECT actor, channel FROM audit_log")
    assert {(r["actor"], r["channel"]) for r in audit} == {("owner@example.com", "web")}
    change = runtime.store.one("SELECT actor, channel FROM change_log")
    assert (change["actor"], change["channel"]) == ("owner@example.com", "web")


def test_older_rows_lose_the_channel_from_their_actor(world):
    client, headers, runtime = world
    store = runtime.store
    store.execute(
        "INSERT INTO pending_actions (id, tool, params, summary, channel, actor, created_at, "
        "expires_at, status) VALUES ('act_old', 'refund', '{}', 'Refund', 'telegram', "
        "'owner@example.com via telegram', 1, 2, 'cancelled')"
    )
    for actor, channel, outcome in [
        ("owner@example.com via telegram", "telegram", "cancelled"),
        ("desk@example.com via api", "web", "pin_set"),  # names another channel: kept
        ("owner", "cli", "pin_set"),  # the CLI's old default: no suffix
    ]:
        store.execute(
            "INSERT INTO audit_log (at, action_id, tool, outcome, actor, channel) "
            "VALUES (1, 'act_old', 'refund', ?, ?, ?)",
            (outcome, actor, channel),
        )
    store.execute(
        "INSERT INTO change_log (at, actor, what) VALUES (1, 'owner@example.com via setup', "
        "'setup.owner')"
    )

    rows = {r["id"]: r for r in client.get("/v1/admin/actions", headers=headers).json()}
    old = rows["act_old"]
    assert (old["actor"], old["channel"]) == ("owner@example.com", "telegram")
    assert (old["decided_by"], old["decided_channel"]) == ("owner@example.com", "telegram")

    audit = client.get("/v1/admin/audit", headers=headers).json()
    assert [(r["actor"], r["channel"]) for r in audit[:3]] == [
        ("owner", "cli"),
        ("desk@example.com via api", "web"),
        ("owner@example.com", "telegram"),
    ]
    change = client.get("/v1/admin/changes", headers=headers).json()[0]
    assert (change["actor"], change["channel"]) == ("owner@example.com", "setup")


def test_split_actor():
    assert changes.split_actor("a@example.com via web", "web") == ("a@example.com", "web")
    assert changes.split_actor("a@example.com via web", None) == ("a@example.com", "web")
    assert changes.split_actor("a@example.com via web", "api") == ("a@example.com via web", "api")
    assert changes.split_actor("a@example.com", "web") == ("a@example.com", "web")
    assert changes.split_actor(None, "web") == (None, "web")
