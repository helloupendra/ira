"""Pending actions and the PIN that releases them.

The model never executes an action tool. Calling one stores a *pending
action*: the validated parameters, a human summary and an expiry. Code runs
it later, once, after the owner confirms with a PIN:

* each user has their own PIN, stored as a salted PBKDF2 hash, and confirms
  with it (a guard used without accounts has one installation PIN);
* an action can be limited to the roles that may confirm it;
* three wrong PINs in a row lock every action for 15 minutes;
* a Tier 2 action needs only a "yes" from the person who asked
  (``approve``); a Tier 3 action, the default, needs a PIN (``confirm``);
* a pending action expires after 120 seconds. Reads mark overdue ones
  ``expired`` first (``expire_overdue``), so a list, a count and a confirm
  never disagree about one;
* a database compare-and-set moves it from ``pending`` to ``executing``, so
  two confirmations racing each other cannot run it twice;
* every outcome writes one audit row.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from ira import toollog
from ira.security import PIN_ITERATIONS, hash_pin, new_id, verify_pin
from ira.store import CONFIRMING_ROLES, SHARED_PIN_SETTING, Store
from ira.tools.registry import Tool, ToolError, ToolRegistry

log = logging.getLogger("ira.actions")

# The installation PIN, used when confirm() is called without a user.
PIN_SETTING = SHARED_PIN_SETTING

# Where a proposed action can stand. Only "pending" waits for a PIN.
ACTION_STATUSES = ("pending", "executing", "executed", "failed", "cancelled", "expired")

OutcomeStatus = Literal[
    "executed",
    "failed",
    "wrong_pin",
    "locked",
    "expired",
    "not_found",
    "already_done",
    "cancelled",
    "no_pin",
    "not_allowed",
    "needs_pin",
    "confirmed",
]


@dataclass
class PendingAction:
    id: str
    tool: str
    params: dict[str, Any]
    summary: str
    conversation_id: str | None
    channel: str | None
    actor: str | None
    created_at: float
    expires_at: float
    status: str
    tier: int = 3
    user_id: int | None = None  # who asked
    device_id: int | None = None  # a device's tool, run there once confirmed

    def public(self, now: float | None = None) -> dict[str, Any]:
        """What a client may see: no parameters beyond the summary."""
        now = time.time() if now is None else now
        return {
            "id": self.id,
            "tool": self.tool,
            "summary": self.summary,
            "status": self.status,
            "expires_in": max(0, round(self.expires_at - now)) if self.status == "pending" else 0,
            # Whole seconds, exactly as a device signs it to approve with its key.
            "expires_at": int(self.expires_at),
            "tier": self.tier,
        }


@dataclass
class Outcome:
    status: OutcomeStatus
    message: str
    action: PendingAction | None = None
    result: Any = None
    attempts_left: int | None = None
    locked_until: float | None = None

    @property
    def ok(self) -> bool:
        return self.status == "executed"

    def public(self) -> dict[str, Any]:
        body: dict[str, Any] = {"status": self.status, "message": self.message}
        if self.action is not None:
            body["action"] = self.action.public()
        if self.result is not None:
            body["result"] = self.result
        if self.attempts_left is not None:
            body["attempts_left"] = self.attempts_left
        if self.locked_until is not None:
            body["locked_seconds"] = max(0, round(self.locked_until - time.time()))
            body["locked_until"] = self.locked_until
        return body


def _row_to_action(row: Any) -> PendingAction:
    return PendingAction(
        id=row["id"],
        tool=row["tool"],
        params=json.loads(row["params"]),
        summary=row["summary"],
        conversation_id=row["conversation_id"],
        channel=row["channel"],
        actor=row["actor"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        status=row["status"],
        tier=3 if row["tier"] is None else int(row["tier"]),
        user_id=row["user_id"],
        device_id=row["device_id"],
    )


def _subject(user_id: int | None) -> int:
    """Whose PIN lock: a person's, or 0 for the installation PIN."""
    return user_id if user_id is not None else 0


class ActionGuard:
    def __init__(
        self,
        store: Store,
        registry: ToolRegistry,
        *,
        expiry_seconds: float = 120,
        max_wrong_pins: int = 3,
        lock_seconds: float = 15 * 60,
        pin_iterations: int = PIN_ITERATIONS,
        confirm_roles: Sequence[str] = CONFIRMING_ROLES,
        tool_confirm_roles: Mapping[str, Sequence[str]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.registry = registry
        self.expiry_seconds = expiry_seconds
        self.max_wrong_pins = max_wrong_pins
        self.lock_seconds = lock_seconds
        self.pin_iterations = pin_iterations
        self.confirm_roles = tuple(confirm_roles)
        self.tool_confirm_roles = {k: tuple(v) for k, v in (tool_confirm_roles or {}).items()}
        self.clock = clock
        # Runs a confirmed action that belongs to a device rather than the registry.
        self.device_runner: Callable[[PendingAction], Awaitable[Any]] | None = None
        # Runs a confirmed action of a person's own tool (a connection's): set by the runtime.
        self.personal_runner: Callable[[PendingAction], Awaitable[Any]] | None = None
        # One PIN check at a time per person (a lock each), so guesses cannot race.
        self._pin_checks: dict[int, asyncio.Lock] = {}
        # Told of each action confirmed with a right PIN (approval windows).
        self.after_pin: Callable[[PendingAction], None] | None = None
        # Checks a device's signature over an action: (user, device, action, signature).
        self.signature_check: Callable[[int, int, PendingAction, str], bool] | None = None

    def confirm_roles_for(self, tool: str) -> tuple[str, ...]:
        """The roles allowed to confirm this action (they also need the actions permission)."""
        return self.tool_confirm_roles.get(tool, self.confirm_roles)

    # PIN management.

    def set_pin(
        self,
        pin: str,
        *,
        user_id: int | None = None,
        actor: str = "owner",
        channel: str = "cli",
        unlock: bool = False,
    ) -> None:
        """Set a user's PIN, or the installation PIN when there is no user.

        ``unlock`` also lifts a wrong-PIN lock; only the server's operator (the
        CLI) does that, so a new PIN cannot be used to skip a lock.
        """
        hashed = hash_pin(pin, iterations=self.pin_iterations)
        if user_id is None:
            self.store.set_setting(PIN_SETTING, hashed)
            unlock = True
        else:
            cursor = self.store.execute(
                "UPDATE users SET pin_hash = ?, pin_set_at = ? "
                "WHERE id = ? AND disabled_at IS NULL",
                (hashed, self.clock(), user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("no such user")
        if unlock:
            self.store.execute(
                "UPDATE pin_locks SET failures = 0, locked_until = 0 WHERE subject = ?",
                (_subject(user_id),),
            )
        self._audit(None, None, "pin_set", actor, channel, None)

    def clear_pin(self, user_id: int, *, actor: str, channel: str = "web") -> bool:
        """Remove a user's PIN. They cannot confirm actions until they set a new one."""
        cursor = self.store.execute(
            "UPDATE users SET pin_hash = NULL, pin_set_at = NULL WHERE id = ?", (user_id,)
        )
        if cursor.rowcount == 1:
            self._audit(None, None, "pin_cleared", actor, channel, None)
        return cursor.rowcount == 1

    def _stored_pin(self, user_id: int | None) -> str | None:
        if user_id is None:
            return self.store.get_setting(PIN_SETTING)
        row = self.store.one(
            "SELECT pin_hash FROM users WHERE id = ? AND disabled_at IS NULL", (user_id,)
        )
        return row["pin_hash"] if row else None

    def has_pin(self, user_id: int | None = None) -> bool:
        return self._stored_pin(user_id) is not None

    def pin_set_at(self, user_id: int) -> float | None:
        """When a user last set their PIN; None without one, or when it was not recorded."""
        row = self.store.one(
            "SELECT pin_set_at FROM users WHERE id = ? AND pin_hash IS NOT NULL "
            "AND disabled_at IS NULL",
            (user_id,),
        )
        return row["pin_set_at"] if row else None

    def wrong_pins(self, user_id: int | None = None, *, anyone: bool = False) -> int:
        """Wrong PINs counted towards the lock: one person's (the installation PIN's without
        a user), or with ``anyone`` everybody's together."""
        if anyone:
            row = self.store.one("SELECT COALESCE(SUM(failures), 0) AS n FROM pin_locks")
        else:
            row = self.store.one(
                "SELECT failures AS n FROM pin_locks WHERE subject = ?", (_subject(user_id),)
            )
        return int(row["n"]) if row else 0

    def locked_until(self, user_id: int | None = None, *, anyone: bool = False) -> float | None:
        """When one person's PIN lock ends (or, with ``anyone``, the latest anybody's)."""
        if anyone:
            row = self.store.one("SELECT MAX(locked_until) AS until FROM pin_locks")
        else:
            row = self.store.one(
                "SELECT locked_until AS until FROM pin_locks WHERE subject = ?",
                (_subject(user_id),),
            )
        until = float(row["until"] or 0) if row else 0.0
        return until if until > self.clock() else None

    async def _checked(
        self, user_id: int | None, check: Callable[[], Awaitable[bool]]
    ) -> tuple[str, float | None]:
        """Check one person's PIN (or signature) one attempt at a time, so that many guesses
        at once cannot all get past the lock: a wrong one is counted, and the lock set,
        before the next is checked. Returns ("ok" | "wrong" | "wrong_locked" | "locked",
        the lock's end): "locked" when it was locked already and nothing was checked."""
        lock = self._pin_checks.setdefault(_subject(user_id), asyncio.Lock())
        async with lock:
            until = self.locked_until(user_id)
            if until is not None:
                return "locked", until
            if await check():
                self._right_pin(user_id)
                return "ok", None
            subject = _subject(user_id)
            self.store.execute("INSERT OR IGNORE INTO pin_locks (subject) VALUES (?)", (subject,))
            self.store.execute(
                "UPDATE pin_locks SET failures = failures + 1 WHERE subject = ?", (subject,)
            )
            if self.wrong_pins(user_id) >= self.max_wrong_pins:
                until = self.clock() + self.lock_seconds
                self.store.execute(
                    "UPDATE pin_locks SET failures = 0, locked_until = ? WHERE subject = ?",
                    (until, subject),
                )
                return "wrong_locked", until
            return "wrong", None

    def _right_pin(self, user_id: int | None) -> None:
        self.store.execute(
            "UPDATE pin_locks SET failures = 0, locked_until = 0 WHERE subject = ?",
            (_subject(user_id),),
        )

    def _locked(self, until: float, actor: str | None, channel: str | None, pending=None):
        return self._finish(
            pending,
            "locked",
            "Actions are locked after too many wrong PINs. Try again later.",
            actor,
            channel,
            locked_until=until,
        )

    # Proposing.

    def propose(
        self,
        tool: Tool,
        args: BaseModel,
        *,
        conversation_id: str | None = None,
        channel: str | None = None,
        actor: str | None = None,
        user_id: int | None = None,
    ) -> PendingAction:
        """Store a pending action. Raises ToolError if the summary refuses it."""
        if tool.kind != "action":
            raise ValueError(f"'{tool.name}' is a read tool, not an action")
        summary = tool.describe(args)  # may raise ToolError
        return self._store_proposal(
            tool.name,
            args.model_dump(mode="json"),
            summary,
            tool.tier,
            conversation_id=conversation_id,
            channel=channel,
            actor=actor,
            user_id=user_id,
        )

    def propose_on_device(
        self,
        tool: str,
        params: dict[str, Any],
        summary: str,
        tier: int,
        *,
        device_id: int,
        user_id: int,
        conversation_id: str | None = None,
        channel: str | None = None,
        actor: str | None = None,
    ) -> PendingAction:
        """Store a pending action that a device runs once it is confirmed."""
        if tier not in (2, 3):
            raise ValueError("only Tier 2 and 3 tools wait for a confirmation")
        return self._store_proposal(
            tool,
            params,
            summary,
            tier,
            conversation_id=conversation_id,
            channel=channel,
            actor=actor,
            user_id=user_id,
            device_id=device_id,
        )

    def propose_personal(
        self,
        tool: str,
        params: dict[str, Any],
        summary: str,
        tier: int,
        *,
        user_id: int,
        conversation_id: str | None = None,
        channel: str | None = None,
        actor: str | None = None,
    ) -> PendingAction:
        """Store a pending action of one person's own tool (a connection's), run once confirmed."""
        if tier not in (2, 3):
            raise ValueError("only Tier 2 and 3 tools wait for a confirmation")
        return self._store_proposal(
            tool,
            params,
            summary,
            tier,
            conversation_id=conversation_id,
            channel=channel,
            actor=actor,
            user_id=user_id,
        )

    def _store_proposal(
        self,
        tool: str,
        params: dict[str, Any],
        summary: str,
        tier: int,
        *,
        conversation_id: str | None,
        channel: str | None,
        actor: str | None,
        user_id: int | None,
        device_id: int | None = None,
    ) -> PendingAction:
        now = self.clock()
        pending = PendingAction(
            id=new_id("act_"),
            tool=tool,
            params=params,
            summary=summary,
            conversation_id=conversation_id,
            channel=channel,
            actor=actor,
            created_at=now,
            expires_at=now + self.expiry_seconds,
            status="pending",
            tier=tier,
            user_id=user_id,
            device_id=device_id,
        )
        self.store.execute(
            "INSERT INTO pending_actions (id, tool, params, summary, conversation_id, channel, "
            "actor, created_at, expires_at, status, tier, user_id, device_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pending.id,
                pending.tool,
                json.dumps(pending.params),
                pending.summary,
                conversation_id,
                channel,
                actor,
                pending.created_at,
                pending.expires_at,
                pending.status,
                tier,
                user_id,
                device_id,
            ),
        )
        self._audit(pending.id, tool, "proposed", actor, channel, summary)
        return pending

    def get(self, action_id: str) -> PendingAction | None:
        row = self.store.one("SELECT * FROM pending_actions WHERE id = ?", (action_id,))
        return _row_to_action(row) if row else None

    def expire_overdue(self) -> int:
        """Mark every pending action past its expiry as expired. Returns how many.

        Called before anything reads action statuses, so an overdue proposal
        never reads as pending. ``finished_at`` is the moment it expired.
        """
        cursor = self.store.execute(
            "UPDATE pending_actions SET status = 'expired', finished_at = expires_at "
            "WHERE status = 'pending' AND expires_at <= ?",
            (self.clock(),),
        )
        return cursor.rowcount

    def _expired(self, pending: PendingAction) -> bool:
        """Whether this action has expired, marking it so if its time just ran out."""
        if pending.status == "pending" and self.clock() >= pending.expires_at:
            self.expire_overdue()
            pending.status = "expired"
        return pending.status == "expired"

    def latest_pending(self, conversation_id: str) -> PendingAction | None:
        """The newest still-valid proposal in a conversation (used by chat channels)."""
        row = self.store.one(
            "SELECT * FROM pending_actions WHERE conversation_id = ? AND status = 'pending' "
            "AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
            (conversation_id, self.clock()),
        )
        return _row_to_action(row) if row else None

    def awaiting_yes(self, conversation_id: str, user_id: int | None) -> PendingAction | None:
        """The newest Tier 2 proposal in a conversation that this person may say yes to."""
        pending = self.latest_pending(conversation_id)
        if pending is None or pending.tier != 2 or pending.user_id != user_id:
            return None
        return pending

    # Confirming new grants (pairing a device, switching a skill on) with a PIN.

    async def check_pin(
        self, pin: str, *, user_id: int, what: str, actor: str | None, channel: str | None
    ) -> Outcome:
        """Check a person's own PIN for something that is not a pending action.

        Wrong PINs count towards the same lock as actions, and the outcome is
        audited with ``what`` as its detail: "confirmed", or why not.
        """
        locked = self.locked_until(user_id)
        if locked is not None:
            return self._locked(locked, actor, channel)
        stored = self._stored_pin(user_id)
        if stored is None:
            message = "You have no action PIN yet. Set your PIN in the Ira app's menu first."
            return self._finish(None, "no_pin", message, actor, channel)
        verdict, until = await self._checked(
            user_id, lambda: asyncio.to_thread(verify_pin, pin, stored)
        )
        if verdict == "locked":
            return self._locked(until, actor, channel, None)
        if verdict != "ok":
            return self._wrong_pin(None, actor, channel, user_id, until)
        return self._finish(None, "confirmed", what, actor, channel)

    # Confirming and cancelling.

    async def confirm(
        self,
        action_id: str,
        pin: str | None,
        *,
        actor: str | None = None,
        channel: str | None = None,
        user_id: int | None = None,
        role: str | None = None,
        signed: tuple[int, str] | None = None,
    ) -> Outcome:
        """Check the PIN and run the action once.

        With ``user_id`` the PIN is that user's own and ``role`` must be allowed
        to confirm this action; without, the installation PIN is checked.
        ``signed`` is (device id, signature) instead of the PIN: the person's device
        signed this action with its enrolled key, after their fingerprint. A wrong
        signature counts as a wrong PIN.
        """
        locked = self.locked_until(user_id)
        if locked is not None:
            return self._locked(locked, actor, channel)

        pending = self.get(action_id)
        if pending is None:
            return self._finish(None, "not_found", "No such action.", actor, channel)
        if self._expired(pending):
            # Whether a read marked it already or its time ran out just now.
            return self._finish(
                pending,
                "expired",
                "This action expired. Ask again to re-propose it.",
                actor,
                channel,
            )
        if pending.status != "pending":
            return self._finish(
                pending, "already_done", f"This action is already {pending.status}.", actor, channel
            )

        allowed = self.confirm_roles_for(pending.tool)
        if role is not None and role not in allowed:
            return self._finish(
                pending,
                "not_allowed",
                f"Your role cannot confirm this action. Allowed: {', '.join(allowed) or 'nobody'}.",
                actor,
                channel,
            )

        if signed is not None:
            if self.signature_check is None or user_id is None:
                message = "This server cannot check a device's approval key."
                return self._finish(pending, "not_allowed", message, actor, channel)
            device_id, signature = signed
            check = self.signature_check

            async def signature_ok() -> bool:
                return check(user_id, device_id, pending, signature)

            verdict, until = await self._checked(user_id, signature_ok)
            if verdict == "locked":
                return self._locked(until, actor, channel, pending)
            if verdict != "ok":
                return self._wrong_pin(pending, actor, channel, user_id, until)
        else:
            stored = self._stored_pin(user_id)
            if stored is None:
                message = (
                    "No action PIN is set. Run `ira pin set` first."
                    if user_id is None
                    else "You have no action PIN yet. "
                    "Set your PIN in the Ira app's menu, or ask an owner to reset it."
                )
                return self._finish(pending, "no_pin", message, actor, channel)

            # PBKDF2 is deliberately slow; keep it off the event loop.
            async def pin_ok() -> bool:
                return bool(pin) and await asyncio.to_thread(verify_pin, pin, stored)

            verdict, until = await self._checked(user_id, pin_ok)
            if verdict == "locked":
                return self._locked(until, actor, channel, pending)
            if verdict != "ok":
                return self._wrong_pin(pending, actor, channel, user_id, until)

        # Claimed once, and only while it has not expired, even if the PIN took a while.
        claimed = self.store.execute(
            "UPDATE pending_actions SET status = 'executing' "
            "WHERE id = ? AND status = 'pending' AND expires_at > ?",
            (pending.id, self.clock()),
        )
        if claimed.rowcount != 1:
            current = self.get(pending.id) or pending
            if current.status == "pending":
                return self._finish(
                    current,
                    "expired",
                    "This action expired. Ask again to re-propose it.",
                    actor,
                    channel,
                )
            return self._finish(
                current, "already_done", f"This action is already {current.status}.", actor, channel
            )
        pending.status = "executing"
        outcome = await self._execute(pending, actor, channel)
        if self.after_pin is not None and outcome.status in ("executed", "failed"):
            self.after_pin(pending)  # the PIN was right: an approval window may open
        return outcome

    async def approve(
        self,
        action_id: str,
        *,
        user_id: int | None,
        actor: str | None = None,
        channel: str | None = None,
    ) -> Outcome:
        """Run a Tier 2 action on a "yes" from the person who asked. No PIN.

        A Tier 3 action answers ``needs_pin``; someone else's answers ``not_allowed``.
        """
        pending = self.get(action_id)
        if pending is None:
            return self._finish(None, "not_found", "No such action.", actor, channel)
        if self._expired(pending):
            return self._finish(
                pending,
                "expired",
                "This action expired. Ask again to re-propose it.",
                actor,
                channel,
            )
        if pending.status != "pending":
            return self._finish(
                pending, "already_done", f"This action is already {pending.status}.", actor, channel
            )
        if pending.tier != 2:
            return self._finish(
                pending, "needs_pin", "This action needs your PIN, not just a yes.", actor, channel
            )
        if pending.user_id is None or pending.user_id != user_id:
            return self._finish(
                pending,
                "not_allowed",
                "Only the person who asked for this can say yes to it.",
                actor,
                channel,
            )
        if not self._set_status(pending.id, "executing", "pending"):
            current = self.get(pending.id) or pending
            return self._finish(
                current, "already_done", f"This action is already {current.status}.", actor, channel
            )
        pending.status = "executing"
        return await self._execute(pending, actor, channel)

    def cancel(
        self, action_id: str, *, actor: str | None = None, channel: str | None = None
    ) -> Outcome:
        pending = self.get(action_id)
        if pending is None:
            return self._finish(None, "not_found", "No such action.", actor, channel)
        if self._expired(pending):
            message = "This action had already expired. Nothing was changed."
            return self._finish(pending, "expired", message, actor, channel)
        if not self._set_status(pending.id, "cancelled", "pending"):
            current = self.get(pending.id) or pending
            return self._finish(
                current, "already_done", f"This action is already {current.status}.", actor, channel
            )
        pending.status = "cancelled"
        return self._finish(pending, "cancelled", "Cancelled. Nothing was changed.", actor, channel)

    # Internals.

    def _wrong_pin(
        self,
        pending: PendingAction | None,
        actor: str | None,
        channel: str | None,
        user_id: int | None = None,
        until: float | None = None,
    ) -> Outcome:
        """A wrong PIN (or signature), already counted; ``until`` when it, or an earlier
        one, locked actions."""
        failures = self.wrong_pins(user_id)
        if until is not None:
            minutes = round(self.lock_seconds / 60)
            return self._finish(
                pending,
                "locked",
                f"Wrong PIN. Actions are now locked for {minutes} minutes.",
                actor,
                channel,
                locked_until=until,
            )
        left = self.max_wrong_pins - failures
        return self._finish(
            pending,
            "wrong_pin",
            f"Wrong PIN. {left} attempt{'s' if left != 1 else ''} left before actions lock.",
            actor,
            channel,
            attempts_left=left,
        )

    async def _execute(
        self, pending: PendingAction, actor: str | None, channel: str | None
    ) -> Outcome:
        started = time.monotonic()
        try:
            result = await self._run(pending)
        except ToolError as exc:
            outcome = self._failed(pending, str(exc), actor, channel)
            self._finished(pending, "failed", started)
            return outcome
        except Exception as exc:
            log.exception("action %s (%s) raised", pending.id, pending.tool)
            outcome = self._failed(
                pending, f"the action raised {type(exc).__name__}", actor, channel
            )
            self._finished(pending, "failed", started)
            return outcome
        self._finished(pending, "executed", started)

        self.store.execute(
            "UPDATE pending_actions SET status = 'executed', result = ?, finished_at = ? "
            "WHERE id = ?",
            (json.dumps(result, default=str), self.clock(), pending.id),
        )
        pending.status = "executed"
        return self._finish(
            pending, "executed", f"Done: {pending.summary}.", actor, channel, result=result
        )

    async def _run(self, pending: PendingAction) -> Any:
        if pending.device_id is not None:
            if self.device_runner is None:
                raise ToolError("devices are not available on this server")
            return await self.device_runner(pending)
        tool = self.registry.get(pending.tool)
        if tool is None and self.personal_runner is not None and pending.user_id is not None:
            return await self.personal_runner(pending)
        if tool is None:
            raise ToolError(f"the tool '{pending.tool}' is no longer registered")
        if not self.registry.is_enabled(tool.name):
            raise ToolError(f"the tool '{tool.name}' is switched off")
        args = tool.validate(pending.params)
        positional, keywords = tool.call_args(args)
        if inspect.iscoroutinefunction(tool.fn):
            return await tool.fn(*positional, **keywords)
        return await asyncio.to_thread(tool.fn, *positional, **keywords)

    def _finished(self, pending: PendingAction, outcome: str, started: float) -> None:
        """Write the run to "What Ira did", for the person who asked."""
        toollog.record(
            self.store,
            tool=pending.tool,
            tier=pending.tier,
            outcome=outcome,
            user_id=pending.user_id,
            channel=pending.channel,
            conversation_id=pending.conversation_id,
            device_id=pending.device_id,
            seconds=time.monotonic() - started,
            clock=self.clock,
        )

    def _failed(
        self, pending: PendingAction, reason: str, actor: str | None, channel: str | None
    ) -> Outcome:
        self.store.execute(
            "UPDATE pending_actions SET status = 'failed', result = ?, finished_at = ? "
            "WHERE id = ?",
            (json.dumps({"error": reason}), self.clock(), pending.id),
        )
        pending.status = "failed"
        return self._finish(pending, "failed", f"The action failed: {reason}", actor, channel)

    def _set_status(self, action_id: str, status: str, expected: str) -> bool:
        cursor = self.store.execute(
            "UPDATE pending_actions SET status = ?, finished_at = ? WHERE id = ? AND status = ?",
            (status, self.clock(), action_id, expected),
        )
        return cursor.rowcount == 1

    def _finish(
        self,
        pending: PendingAction | None,
        status: OutcomeStatus,
        message: str,
        actor: str | None,
        channel: str | None,
        **extra: Any,
    ) -> Outcome:
        self._audit(
            pending.id if pending else None,
            pending.tool if pending else None,
            status,
            actor,
            channel,
            message,
        )
        return Outcome(status=status, message=message, action=pending, **extra)

    def _audit(
        self,
        action_id: str | None,
        tool: str | None,
        outcome: str,
        actor: str | None,
        channel: str | None,
        detail: str | None,
    ) -> None:
        self.store.execute(
            "INSERT INTO audit_log (at, action_id, tool, outcome, actor, channel, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.clock(), action_id, tool, outcome, actor, channel, detail),
        )

    def audit(self, limit: int = 50, before_id: int | None = None) -> list[dict[str, Any]]:
        """Audit rows, newest first; ``before_id`` keeps rows older than that id."""
        rows = self.store.query(
            "SELECT * FROM audit_log WHERE id < ? ORDER BY id DESC LIMIT ?",
            (before_id if before_id is not None else 2**62, limit),
        )
        return [dict(row) for row in rows]
