"""The change log: every change made from the admin console, with who, what and when.

Action outcomes have their own audit log (``audit_log``); this one records
the console's writes: users, invites, tokens, tools, model chains, settings.
Values are stored as JSON, and secrets never appear in them.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from ira.store import Store

# Rows written before v0.2 put the channel into the actor: "owner@example.com via web".
_VIA = re.compile(r"^(?P<who>.+) via (?P<channel>[a-z]+)$")


def split_actor(actor: str | None, channel: str | None) -> tuple[str | None, str | None]:
    """(person, channel) for a stored row, cleaning an older "x via web" actor.

    The trailing " via <channel>" is dropped when it names the row's channel,
    or gives the channel when the row has none (the change log had no column).
    """
    match = _VIA.match(actor or "")
    if match and channel in (None, match["channel"]):
        return match["who"], match["channel"]
    return actor, channel


def record(
    store: Store,
    actor: str,
    what: str,
    target: str | None = None,
    *,
    channel: str | None = None,
    before: Any = None,
    after: Any = None,
) -> None:
    """Write one change. ``actor`` is the person (an email); ``channel`` where they were."""
    store.execute(
        "INSERT INTO change_log (at, actor, channel, what, target, before, after) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            time.time(),
            actor,
            channel,
            what,
            target,
            None if before is None else json.dumps(before, default=str),
            None if after is None else json.dumps(after, default=str),
        ),
    )


def recent(store: Store, limit: int = 100, before_id: int | None = None) -> list[dict[str, Any]]:
    rows = store.query(
        "SELECT * FROM change_log WHERE id < ? ORDER BY id DESC LIMIT ?",
        (before_id if before_id is not None else 2**62, limit),
    )
    out = []
    for row in rows:
        item = dict(row)
        item["actor"], item["channel"] = split_actor(row["actor"], row["channel"])
        item["before"] = json.loads(row["before"]) if row["before"] is not None else None
        item["after"] = json.loads(row["after"]) if row["after"] is not None else None
        out.append(item)
    return out
