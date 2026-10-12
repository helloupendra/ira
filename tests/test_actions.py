"""The action / PIN flow: propose, confirm once, lock, expire, audit."""

from __future__ import annotations

import asyncio

import pytest

from ira.security import hash_pin, verify_pin
from ira.tools.actions import ActionGuard
from ira.tools.registry import ToolError, ToolRegistry

from .conftest import FAST_PIN_ITERATIONS

pytestmark = pytest.mark.anyio

PIN = "4321"


@pytest.fixture
def guard(store, registry, clock) -> ActionGuard:
    g = ActionGuard(store, registry, pin_iterations=FAST_PIN_ITERATIONS, clock=clock)
    g.set_pin(PIN)
    return g


def propose(guard: ActionGuard, order_id: str = "A1", amount: int = 50):
    tool = guard.registry.get("refund")
    return guard.propose(tool, tool.validate({"order_id": order_id, "amount": amount}))


def outcomes(store) -> list[str]:
    return [r["outcome"] for r in store.query("SELECT outcome FROM audit_log ORDER BY id")]


async def test_proposing_does_not_execute(guard, ledger):
    pending = propose(guard)
    assert pending.status == "pending"
    assert pending.summary == "Refund 50 on order A1"
    assert ledger.refunds == []


async def test_the_right_pin_executes_exactly_once(guard, ledger, store):
    pending = propose(guard)

    first = await guard.confirm(pending.id, PIN)
    second = await guard.confirm(pending.id, PIN)

    assert first.status == "executed" and first.result == {"refunded": 50}
    assert second.status == "already_done"
    assert ledger.refunds == [("A1", 50)]
    assert outcomes(store) == ["pin_set", "proposed", "executed", "already_done"]


async def test_racing_confirmations_run_the_action_once(store, registry, clock, ledger):
    guard = ActionGuard(store, registry, pin_iterations=FAST_PIN_ITERATIONS, clock=clock)
    guard.set_pin(PIN)
    pending = propose(guard)

    results = await asyncio.gather(*(guard.confirm(pending.id, PIN) for _ in range(5)))

    assert sorted(r.status for r in results) == ["already_done"] * 4 + ["executed"]
    assert ledger.refunds == [("A1", 50)]


async def test_three_wrong_pins_lock_actions_for_fifteen_minutes(guard, ledger, clock):
    pending = propose(guard)

    first = await guard.confirm(pending.id, "0000")
    second = await guard.confirm(pending.id, "1111")
    third = await guard.confirm(pending.id, "2222")
    assert [first.status, second.status, third.status] == ["wrong_pin", "wrong_pin", "locked"]
    assert first.attempts_left == 2

    # While locked even the right PIN is refused, and nothing runs.
    clock.advance(60)
    locked = await guard.confirm(propose(guard).id, PIN)
    assert locked.status == "locked"
    assert ledger.refunds == []

    clock.advance(15 * 60)
    fresh = propose(guard)
    assert (await guard.confirm(fresh.id, PIN)).status == "executed"


async def test_a_correct_pin_resets_the_wrong_pin_count(guard):
    await guard.confirm(propose(guard).id, "0000")
    await guard.confirm(propose(guard).id, "0000")
    assert (await guard.confirm(propose(guard).id, PIN)).status == "executed"
    # The count starts again: two more wrong PINs do not lock.
    assert (await guard.confirm(propose(guard).id, "0000")).status == "wrong_pin"
    assert (await guard.confirm(propose(guard).id, "0000")).status == "wrong_pin"


async def test_actions_expire_after_120_seconds(guard, ledger, clock, store):
    pending = propose(guard)
    clock.advance(121)

    outcome = await guard.confirm(pending.id, PIN)

    assert outcome.status == "expired"
    assert ledger.refunds == []
    assert guard.get(pending.id).status == "expired"
    assert guard.latest_pending("any") is None


async def test_cancel_and_unknown_ids(guard, ledger):
    pending = propose(guard)
    assert guard.cancel(pending.id).status == "cancelled"
    assert (await guard.confirm(pending.id, PIN)).status == "already_done"
    assert (await guard.confirm("act_missing", PIN)).status == "not_found"
    assert ledger.refunds == []


async def test_no_pin_set_means_nothing_runs(store, registry, ledger):
    guard = ActionGuard(store, registry, pin_iterations=FAST_PIN_ITERATIONS)
    pending = propose(guard)
    assert (await guard.confirm(pending.id, PIN)).status == "no_pin"
    assert ledger.refunds == []


async def test_a_summary_can_refuse_a_proposal(guard):
    with pytest.raises(ToolError, match="no order"):
        propose(guard, order_id="missing")


async def test_a_failing_action_is_recorded_as_failed(store, clock):
    reg = ToolRegistry()

    @reg.action
    def explode() -> dict:
        """Always fails."""
        raise ToolError("the payment service said no")

    guard = ActionGuard(store, reg, pin_iterations=FAST_PIN_ITERATIONS, clock=clock)
    guard.set_pin(PIN)
    tool = reg.get("explode")
    pending = guard.propose(tool, tool.validate({}))

    outcome = await guard.confirm(pending.id, PIN)

    assert outcome.status == "failed"
    assert "payment service said no" in outcome.message
    assert guard.get(pending.id).status == "failed"


def test_pin_hash_is_salted_pbkdf2():
    first = hash_pin(PIN, iterations=FAST_PIN_ITERATIONS)
    second = hash_pin(PIN, iterations=FAST_PIN_ITERATIONS)
    assert first.startswith(f"pbkdf2_sha256${FAST_PIN_ITERATIONS}$")
    assert first != second  # different salts
    assert PIN not in first
    assert verify_pin(PIN, first) and not verify_pin("1234", first)
    assert not verify_pin(PIN, "garbage")
    with pytest.raises(ValueError):
        hash_pin("12ab")


# Per-user PINs and confirm roles (v0.2).

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret


@pytest.fixture
def people(store):
    from ira.accounts import Accounts

    accounts = Accounts(store)
    owner = accounts.create_first_owner("owner@example.com", PASSWORD)
    staff = accounts.create_user("desk@example.com", PASSWORD, "staff")
    return owner, staff


async def test_each_user_confirms_with_their_own_pin(store, registry, clock, people, ledger):
    owner, staff = people
    guard = ActionGuard(store, registry, pin_iterations=FAST_PIN_ITERATIONS, clock=clock)
    guard.set_pin("1111", user_id=owner.id)
    guard.set_pin("2222", user_id=staff.id)

    wrong = await guard.confirm(propose(guard).id, "1111", user_id=staff.id, role="staff")
    assert wrong.status == "wrong_pin"
    right = await guard.confirm(propose(guard).id, "2222", user_id=staff.id, role="staff")
    assert right.status == "executed"
    assert len(ledger.refunds) == 1


async def test_a_user_without_a_pin_cannot_confirm(store, registry, people, ledger):
    owner, _ = people
    guard = ActionGuard(store, registry, pin_iterations=FAST_PIN_ITERATIONS)
    guard.set_pin(PIN)  # the installation PIN does not stand in for a user's own
    outcome = await guard.confirm(propose(guard).id, PIN, user_id=owner.id, role="owner")
    assert outcome.status == "no_pin"
    # There is no Account page: say where a PIN is really set.
    assert outcome.message.endswith(
        "Set your PIN in the Ira app's menu, or ask an owner to reset it."
    )
    assert ledger.refunds == []


async def test_clearing_a_pin_stops_confirmations(store, registry, people):
    owner, _ = people
    guard = ActionGuard(store, registry, pin_iterations=FAST_PIN_ITERATIONS)
    guard.set_pin(PIN, user_id=owner.id)
    assert guard.has_pin(owner.id)
    assert guard.clear_pin(owner.id, actor="owner@example.com via web")
    assert not guard.has_pin(owner.id)
    outcome = await guard.confirm(propose(guard).id, PIN, user_id=owner.id, role="owner")
    assert outcome.status == "no_pin"
    assert "pin_cleared" in outcomes(store)


async def test_confirm_roles_can_be_narrowed_per_action(store, registry, people, ledger):
    owner, staff = people
    guard = ActionGuard(
        store,
        registry,
        pin_iterations=FAST_PIN_ITERATIONS,
        tool_confirm_roles={"refund": ["owner"]},
    )
    guard.set_pin(PIN, user_id=owner.id)
    guard.set_pin(PIN, user_id=staff.id)
    assert guard.confirm_roles_for("refund") == ("owner",)
    assert guard.confirm_roles_for("other") == ("owner", "admin", "staff")

    pending = propose(guard)
    refused = await guard.confirm(pending.id, PIN, user_id=staff.id, role="staff")
    assert refused.status == "not_allowed"
    assert guard.wrong_pins() == 0  # refused before the PIN was even checked
    assert guard.get(pending.id).status == "pending"
    allowed = await guard.confirm(pending.id, PIN, user_id=owner.id, role="owner")
    assert allowed.status == "executed"
    assert ledger.refunds == [("A1", 50)]


async def test_a_new_pin_from_the_console_does_not_lift_a_lock(store, registry, clock, people):
    owner, _ = people
    guard = ActionGuard(store, registry, pin_iterations=FAST_PIN_ITERATIONS, clock=clock)
    guard.set_pin(PIN, user_id=owner.id)
    for _ in range(3):
        await guard.confirm(propose(guard).id, "0000", user_id=owner.id, role="owner")
    assert guard.locked_until() is not None
    guard.set_pin("9999", user_id=owner.id, actor="owner@example.com via web", channel="web")
    assert guard.locked_until() is not None
    guard.set_pin("9999", user_id=owner.id, unlock=True)  # what `ira pin set` does
    assert guard.locked_until() is None


async def test_a_switched_off_tool_does_not_run_after_the_pin(guard, ledger):
    pending = propose(guard)
    guard.registry.set_enabled("refund", False)
    outcome = await guard.confirm(pending.id, PIN)
    assert outcome.status == "failed"
    assert "switched off" in outcome.message
    assert ledger.refunds == []


def test_a_v01_installation_pin_is_given_to_everyone_who_could_use_it(tmp_path):
    from ira.accounts import Accounts
    from ira.store import Store

    path = tmp_path / "ira.db"
    first = Store(path)
    accounts = Accounts(first)
    owner = accounts.create_first_owner("owner@example.com", PASSWORD)
    staff = accounts.create_user("desk@example.com", PASSWORD, "staff")
    viewer = accounts.create_user("books@example.com", PASSWORD, "viewer")
    first.set_setting("actions.pin_hash", hash_pin(PIN, iterations=FAST_PIN_ITERATIONS))
    first.close()

    reopened = Store(path)  # what an upgrade does on the first start
    guard = ActionGuard(reopened, ToolRegistry())
    assert guard.has_pin(owner.id) and guard.has_pin(staff.id)
    assert not guard.has_pin(viewer.id)
    assert reopened.get_setting("actions.pin_hash") is None


def test_older_databases_gain_the_new_columns(tmp_path):
    import sqlite3

    from ira.store import Store

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, "
        "password_hash TEXT NOT NULL, role TEXT NOT NULL, created_at REAL NOT NULL, "
        "last_login_at REAL, disabled_at REAL);"
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, "
        "user_id INTEGER NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL, "
        "last_seen_at REAL, revoked_at REAL);"
    )
    conn.close()
    store = Store(path)
    columns = {row["name"] for row in store.query("PRAGMA table_info(users)")}
    assert {"pin_hash", "pin_set_at"} <= columns
    sessions = {row["name"] for row in store.query("PRAGMA table_info(sessions)")}
    assert "user_agent" in sessions
