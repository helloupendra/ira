"""The change log: every change made from the admin console, with who, what and when.

Action outcomes have their own audit log (``audit_log``); this one records
the console's writes: users, invites, tokens, tools, model chains, settings.
Values are stored as JSON, and secrets never appear in them.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ira.store import Store


def record(
    store: Store,
    actor: str,
    what: str,
    target: str | None = None,
    *,
    before: Any = None,
    after: Any = None,
) -> None:
    store.execute(
        "INSERT INTO change_log (at, actor, what, target, before, after) VALUES (?, ?, ?, ?, ?, ?)",
        (
            time.time(),
            actor,
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
        item["before"] = json.loads(row["before"]) if row["before"] is not None else None
        item["after"] = json.loads(row["after"]) if row["after"] is not None else None
        out.append(item)
    return out
