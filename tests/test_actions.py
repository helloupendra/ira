"""The action / PIN flow: propose, confirm once, lock, expire, audit."""

from __future__ import annotations

import asyncio

import pytest

from ira.security import hash_pin, verify_pin
from ira.tools.actions import ActionGuard
from ira.tools.registry import ToolError

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
    from ira.tools.registry import ToolRegistry

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
