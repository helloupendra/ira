"""What Ira did: one row per tool call and per action that ran, for the person it was for.

A row says who, on which channel, which tool, on which device, its tier, the
outcome and how long it took. It never holds the arguments or the result:
those can be page text or other private content.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ira.store import Store

# ok/error: a tool ran (or failed); proposed: an action now waits for a yes or a PIN;
# refused: not run (untrusted content asked for it, or a limit); executed/failed: an
# action ran after its confirmation.
OUTCOMES = ("ok", "error", "proposed", "refused", "executed", "failed")


def record(
    store: Store,
    *,
    tool: str,
    tier: int,
    outcome: str,
    user_id: int | None = None,
    channel: str | None = None,
    conversation_id: str | None = None,
    device_id: int | None = None,
    seconds: float | None = None,
    clock: Callable[[], float] = time.time,
) -> None:
    store.execute(
        "INSERT INTO tool_log (at, user_id, channel, conversation_id, tool, device_id, tier, "
        "outcome, seconds) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            clock(),
            user_id,
            channel,
            conversation_id,
            tool,
            device_id,
            tier,
            outcome,
            None if seconds is None else round(seconds, 3),
        ),
    )


def recent(
    store: Store, user_id: int, limit: int = 100, before_id: int | None = None
) -> list[dict[str, Any]]:
    """One person's rows, newest first, with each device's name."""
    rows = store.query(
        "SELECT l.id, l.at, l.channel, l.tool, l.device_id, d.label AS device, l.tier, "
        "l.outcome, l.seconds FROM tool_log l LEFT JOIN devices d ON d.id = l.device_id "
        "WHERE l.user_id = ? AND l.id < ? ORDER BY l.id DESC LIMIT ?",
        (user_id, before_id if before_id is not None else 2**62, limit),
    )
    return [dict(row) for row in rows]
