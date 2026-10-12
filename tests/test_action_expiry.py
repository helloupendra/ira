"""An expired proposal reads expired everywhere: lists, counts, transcripts and confirm."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider
from ira.store import Store

from .conftest import Clock, make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
PIN = "2468"


def refund(order_id: str) -> ChatResponse:
    arguments = json.dumps({"order_id": order_id, "amount": 5})
    return ChatResponse(text="", tool_calls=[ToolCall("c1", "refund", arguments)])


@pytest.fixture
def world(registry):
    clock = Clock(time.time())
    provider = ScriptedProvider([refund("A1"), "Proposed.", refund("B2"), "Proposed."])
    runtime = make_runtime(provider=provider, registry=registry, clock=clock)
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    runtime.guard.set_pin(PIN, user_id=owner.id)
    session, _ = runtime.accounts.start_session(owner)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        yield client, {"Authorization": f"Bearer {session}"}, runtime, clock


def ask(client, headers, text: str) -> dict:
    body = {"text": text, "conversation_id": "desk"}
    return client.post("/v1/ask", json=body, headers=headers).json()["action"]


def test_an_expired_proposal_reads_expired_in_lists_counts_and_confirm(world):
    client, headers, _, clock = world
    old = ask(client, headers, "refund A1")
    clock.advance(121)  # past its 120 seconds; nothing has looked at it since
    new = ask(client, headers, "refund B2")

    def listed(status: str) -> list[str]:
        rows = client.get(f"/v1/admin/actions?status={status}", headers=headers).json()
        return [row["id"] for row in rows]

    assert listed("pending") == [new["id"]]
    assert listed("expired") == [old["id"]]
    rows = {r["id"]: r for r in client.get("/v1/admin/actions", headers=headers).json()}
    assert rows[old["id"]]["status"] == "expired"
    assert rows[old["id"]]["finished_at"] == rows[old["id"]]["expires_at"]

    overview = client.get("/v1/admin/overview", headers=headers).json()
    assert overview["actions"] == {"pending": 1, "expired": 1}
    counts = client.get("/v1/admin/actions/counts", headers=headers).json()
    assert (counts["pending"], counts["expired"], counts["total"]) == (1, 1, 2)
    assert counts["since"] is None and counts["executed"] == 0

    # Confirming or cancelling the expired one still answers "expired", not "already done".
    late = client.post(f"/v1/actions/{old['id']}/confirm", json={"pin": PIN}, headers=headers)
    assert late.status_code == 410 and late.json()["status"] == "expired"
    dropped = client.post(f"/v1/actions/{old['id']}/cancel", headers=headers)
    assert dropped.status_code == 410 and dropped.json()["status"] == "expired"

    done = client.post(f"/v1/actions/{new['id']}/confirm", json={"pin": PIN}, headers=headers)
    assert done.json()["status"] == "executed"
    counts = client.get("/v1/admin/actions/counts", headers=headers).json()
    assert (counts["pending"], counts["executed"], counts["expired"]) == (0, 1, 1)
    # since counts what was proposed at or after it: here only the newer action.
    recent = client.get(f"/v1/admin/actions/counts?since={clock.now}", headers=headers).json()
    assert (recent["total"], recent["executed"], recent["since"]) == (1, 1, clock.now)


def test_a_transcript_shows_each_proposal_as_it_stands_now(world):
    client, headers, runtime, clock = world
    old = ask(client, headers, "refund A1")
    clock.advance(121)
    new = ask(client, headers, "refund B2")

    for path in ("/v1/conversations/desk", "/v1/admin/conversations/http:1:desk"):
        messages = client.get(path, headers=headers).json()
        proposals = [m for m in messages if m["role"] == "tool"]
        assert [m["action"]["id"] for m in proposals] == [old["id"], new["id"]], path
        assert [m["action"]["status"] for m in proposals] == ["expired", "pending"], path
        assert proposals[0]["action"]["summary"] == "Refund 5 on order A1"
        # What the model saw is kept as it was.
        assert "pending_confirmation" in proposals[0]["content"]
        assert all(m["action"] is None for m in messages if m["role"] != "tool")


def test_the_guard_answers_expired_after_a_read_marked_it(store, registry, clock):
    from ira.tools.actions import ActionGuard

    from .conftest import FAST_PIN_ITERATIONS

    guard = ActionGuard(store, registry, pin_iterations=FAST_PIN_ITERATIONS, clock=clock)
    guard.set_pin(PIN)
    tool = registry.get("refund")
    pending = guard.propose(tool, tool.validate({"order_id": "A1", "amount": 5}))
    assert guard.expire_overdue() == 0
    clock.advance(120)
    assert guard.expire_overdue() == 1
    assert guard.get(pending.id).status == "expired"


@pytest.mark.anyio
async def test_the_guard_answers_expired_on_confirm_after_the_sweep(store, registry, clock):
    from ira.tools.actions import ActionGuard

    from .conftest import FAST_PIN_ITERATIONS

    guard = ActionGuard(store, registry, pin_iterations=FAST_PIN_ITERATIONS, clock=clock)
    guard.set_pin(PIN)
    tool = registry.get("refund")
    pending = guard.propose(tool, tool.validate({"order_id": "A1", "amount": 5}))
    clock.advance(121)
    guard.expire_overdue()
    assert (await guard.confirm(pending.id, PIN)).status == "expired"
    assert guard.cancel(pending.id).status == "expired"


def test_older_transcripts_are_linked_to_the_actions_they_proposed(tmp_path):
    path = tmp_path / "old.db"
    store = Store(path)
    store.execute("ALTER TABLE messages DROP COLUMN action_id")  # as stored before v0.2
    proposal = json.dumps({"status": "pending_confirmation", "summary": "Refund"})

    def action(action_id: str, at: float, conversation: str = "c") -> None:
        store.execute(
            "INSERT INTO pending_actions (id, tool, params, summary, conversation_id, "
            "created_at, expires_at, status) VALUES (?, 'refund', '{}', 'Refund', ?, ?, ?, "
            "'pending')",
            (action_id, conversation, at, at + 120),
        )

    def message(at: float, role: str, content: str, conversation: str = "c") -> None:
        store.execute(
            "INSERT INTO conversations (id, channel, started_at, last_at) VALUES (?, 'web', 0, 0) "
            "ON CONFLICT DO NOTHING",
            (conversation,),
        )
        store.execute(
            "INSERT INTO messages (conversation_id, at, role, content, name) "
            "VALUES (?, ?, ?, ?, ?)",
            (conversation, at, role, content, "refund" if role == "tool" else None),
        )

    message(50, "user", "hello")  # an earlier turn
    action("act_orphan", 100)  # from a turn that crashed before it was stored
    action("act_one", 150)
    action("act_two", 160)
    for role, content in [("user", "refund twice"), ("tool", proposal), ("tool", proposal)]:
        message(170, role, content)
    message(180, "tool", proposal, conversation="lonely")  # no action to match
    store.close()

    reopened = Store(path)
    rows = reopened.query("SELECT conversation_id, action_id FROM messages WHERE role = 'tool'")
    assert [(r["conversation_id"], r["action_id"]) for r in rows] == [
        ("c", "act_one"),
        ("c", "act_two"),
        ("lonely", None),
    ]
