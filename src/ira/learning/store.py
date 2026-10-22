"""What learning keeps, per person: observations, named networks, learnings and reminders.

Observations are only ever recorded for a person who switched learning on,
from a source they switched on, and are kept ``learning_days`` (90 by
default). A place is a label the person chose ("Office"), never coordinates;
a network is a hash made on their own device, never its name.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ira.devices.protocol import clean_line
from ira.security import new_id
from ira.store import Store

KINDS = (
    "lock",
    "unlock",
    "sleep",
    "wake",
    "first_activity",
    "network",
    "arrive",
    "leave",
    "said",
    "feedback",
)
MAC_KINDS = ("lock", "unlock", "sleep", "wake", "first_activity", "network")
PLACE_KINDS = ("arrive", "leave")
MAX_LABEL = 40
FINGERPRINT = re.compile(r"^[0-9a-f]{16,64}$")
# Two decimal numbers that look like latitude and longitude.
COORDINATES = re.compile(r"[-+]?\d{1,3}\.\d{2,}\s*[, ]\s*[-+]?\d{1,3}\.\d{2,}")
STATUSES = ("proposed", "ready", "asked", "active", "rejected", "faded", "changed")


class LearningError(ValueError):
    """A request learning refuses; the message is safe to show."""


def clean_label(value: Any) -> str:
    """A place or network name: one short line, and never coordinates."""
    label = clean_line(value, MAX_LABEL)
    if not label:
        raise LearningError("a place needs a name, such as Office or Home")
    if COORDINATES.search(str(value)):
        raise LearningError("places are names only, never coordinates")
    return label


@dataclass
class Learning:
    id: str
    user_id: int
    kind: str
    key: str
    text: str
    evidence: dict[str, Any]
    confidence: float
    status: str
    created_at: float
    updated_at: float
    asked_at: float | None = None
    decided_at: float | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "key": self.key,
            "text": self.text,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "asked_at": self.asked_at,
            "decided_at": self.decided_at,
        }


def _learning(row: Any) -> Learning:
    return Learning(
        id=row["id"],
        user_id=row["user_id"],
        kind=row["kind"],
        key=row["key"],
        text=row["text"],
        evidence=json.loads(row["evidence"]),
        confidence=row["confidence"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        asked_at=row["asked_at"],
        decided_at=row["decided_at"],
    )


def _row(row: Any) -> dict[str, Any]:
    item = dict(row)
    if "detail" in item:
        item["detail"] = json.loads(item["detail"]) if item["detail"] else {}
    return item


class LearningStore:
    def __init__(self, store: Store, *, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.clock = clock

    # Observations.

    def add(
        self,
        user_id: int,
        kind: str,
        source: str,
        *,
        at: float | None = None,
        label: str | None = None,
        device_id: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> int:
        if kind not in KINDS:
            raise LearningError(f"unknown observation '{kind}'")
        cursor = self.store.execute(
            "INSERT INTO observations (user_id, at, kind, label, source, device_id, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                self.clock() if at is None else at,
                kind,
                label,
                source,
                device_id,
                json.dumps(detail, ensure_ascii=False) if detail else None,
            ),
        )
        return int(cursor.lastrowid or 0)

    def observations(
        self,
        user_id: int,
        *,
        since: float | None = None,
        kinds: tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM observations WHERE user_id = ?"
        params: list[Any] = [user_id]
        if since is not None:
            sql += " AND at >= ?"
            params.append(since)
        if kinds:
            sql += f" AND kind IN ({','.join('?' for _ in kinds)})"
            params += list(kinds)
        sql += " ORDER BY at"
        if limit is not None:
            sql = f"SELECT * FROM ({sql.replace('ORDER BY at', 'ORDER BY at DESC')} LIMIT ?) "
            sql += "ORDER BY at"
            params.append(limit)
        return [_row(r) for r in self.store.query(sql, params)]

    def purge(self, user_id: int, days: int) -> int:
        """Forget observations older than ``days``."""
        cursor = self.store.execute(
            "DELETE FROM observations WHERE user_id = ? AND at < ?",
            (user_id, self.clock() - days * 86400),
        )
        return cursor.rowcount

    def forget_observations(self, user_id: int, ids: list[int]) -> int:
        if not ids:
            return 0
        marks = ",".join("?" for _ in ids)
        cursor = self.store.execute(
            f"DELETE FROM observations WHERE user_id = ? AND id IN ({marks})", (user_id, *ids)
        )
        return cursor.rowcount

    # Networks a person's devices reported, by hash, and the names they gave them.

    def network_seen(self, user_id: int, device_id: int | None, fingerprint: str) -> str | None:
        """Note a network; returns its name if the person gave it one."""
        if not FINGERPRINT.fullmatch(fingerprint):
            raise LearningError("a network is identified by its hash only")
        now = self.clock()
        self.store.execute(
            "INSERT INTO networks (user_id, fingerprint, device_id, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, fingerprint) DO UPDATE SET "
            "last_seen = excluded.last_seen, device_id = excluded.device_id",
            (user_id, fingerprint, device_id, now, now),
        )
        row = self.store.one(
            "SELECT label FROM networks WHERE user_id = ? AND fingerprint = ?",
            (user_id, fingerprint),
        )
        return row["label"] if row else None

    def networks(self, user_id: int) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT n.fingerprint, n.label, n.device_id, d.label AS device, n.first_seen, "
            "n.last_seen FROM networks n LEFT JOIN devices d ON d.id = n.device_id "
            "WHERE n.user_id = ? ORDER BY n.last_seen DESC",
            (user_id,),
        )
        return [dict(r) for r in rows]

    def name_network(self, user_id: int, fingerprint: str, label: str | None) -> bool:
        """Name a network (None forgets the name); past observations on it follow."""
        clean = None if label is None else clean_label(label)
        cursor = self.store.execute(
            "UPDATE networks SET label = ? WHERE user_id = ? AND fingerprint = ?",
            (clean, user_id, fingerprint),
        )
        if cursor.rowcount != 1:
            return False
        self.store.execute(
            "UPDATE observations SET label = ? WHERE user_id = ? AND source = 'mac' "
            "AND json_extract(detail, '$.network') = ?",
            (clean, user_id, fingerprint),
        )
        return True

    def forget_network(self, user_id: int, fingerprint: str) -> bool:
        self.name_network(user_id, fingerprint, None)
        cursor = self.store.execute(
            "DELETE FROM networks WHERE user_id = ? AND fingerprint = ?", (user_id, fingerprint)
        )
        return cursor.rowcount == 1

    # Learnings.

    def learnings(self, user_id: int, statuses: tuple[str, ...] | None = None) -> list[Learning]:
        sql = "SELECT * FROM learnings WHERE user_id = ?"
        params: list[Any] = [user_id]
        if statuses:
            sql += f" AND status IN ({','.join('?' for _ in statuses)})"
            params += list(statuses)
        rows = self.store.query(sql + " ORDER BY created_at", params)
        return [_learning(r) for r in rows]

    def learning(self, user_id: int, learning_id: str) -> Learning | None:
        row = self.store.one(
            "SELECT * FROM learnings WHERE user_id = ? AND id = ?", (user_id, learning_id)
        )
        return _learning(row) if row else None

    def by_key(self, user_id: int, key: str) -> Learning | None:
        row = self.store.one(
            "SELECT * FROM learnings WHERE user_id = ? AND key = ?", (user_id, key)
        )
        return _learning(row) if row else None

    def save(
        self,
        user_id: int,
        kind: str,
        key: str,
        text: str,
        evidence: dict[str, Any],
        confidence: float,
        status: str,
    ) -> Learning:
        now = self.clock()
        existing = self.by_key(user_id, key)
        if existing is None:
            learning_id = new_id("lrn_")
            self.store.execute(
                "INSERT INTO learnings (id, user_id, kind, key, text, evidence, confidence, "
                "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    learning_id,
                    user_id,
                    kind,
                    key,
                    text,
                    json.dumps(evidence, ensure_ascii=False),
                    confidence,
                    status,
                    now,
                    now,
                ),
            )
        else:
            learning_id = existing.id
            self.store.execute(
                "UPDATE learnings SET text = ?, evidence = ?, confidence = ?, status = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    text,
                    json.dumps(evidence, ensure_ascii=False),
                    confidence,
                    status,
                    now,
                    learning_id,
                ),
            )
        learning = self.learning(user_id, learning_id)
        assert learning is not None
        return learning

    def set_status(self, user_id: int, learning_id: str, status: str, **times: float) -> bool:
        if status not in STATUSES:
            raise LearningError(f"unknown status '{status}'")
        fields = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, self.clock()]
        for name in ("asked_at", "decided_at"):
            if name in times:
                fields.append(f"{name} = ?")
                params.append(times[name])
        cursor = self.store.execute(
            f"UPDATE learnings SET {', '.join(fields)} WHERE user_id = ? AND id = ?",
            (*params, user_id, learning_id),
        )
        return cursor.rowcount == 1

    def forget_learning(self, user_id: int, learning_id: str) -> bool:
        cursor = self.store.execute(
            "DELETE FROM learnings WHERE user_id = ? AND id = ?", (user_id, learning_id)
        )
        return cursor.rowcount == 1

    # Reminders.

    def add_reminder(
        self,
        user_id: int,
        text: str,
        *,
        trigger: str,
        due_at: float | None = None,
        place: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        reminder_id = new_id("rem_")
        self.store.execute(
            "INSERT INTO reminders (id, user_id, text, due_at, trigger, place, created_at, "
            "conversation_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (reminder_id, user_id, text, due_at, trigger, place, self.clock(), conversation_id),
        )
        return self.reminder(user_id, reminder_id) or {}

    def reminder(self, user_id: int, reminder_id: str) -> dict[str, Any] | None:
        row = self.store.one(
            "SELECT * FROM reminders WHERE user_id = ? AND id = ?", (user_id, reminder_id)
        )
        return dict(row) if row else None

    def reminders(self, user_id: int, *, open_only: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM reminders WHERE user_id = ?"
        if open_only:
            sql += " AND done_at IS NULL"
        return [dict(r) for r in self.store.query(sql + " ORDER BY created_at", (user_id,))]

    def due_reminders(self, now: float) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT * FROM reminders WHERE done_at IS NULL AND trigger = 'time' AND due_at <= ?",
            (now,),
        )
        return [dict(r) for r in rows]

    def place_reminders(self, user_id: int, trigger: str, place: str) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT * FROM reminders WHERE user_id = ? AND done_at IS NULL AND trigger = ? "
            "AND lower(place) = lower(?)",
            (user_id, trigger, place),
        )
        return [dict(r) for r in rows]

    def finish_reminder(self, reminder_id: str) -> bool:
        cursor = self.store.execute(
            "UPDATE reminders SET done_at = ? WHERE id = ? AND done_at IS NULL",
            (self.clock(), reminder_id),
        )
        return cursor.rowcount == 1

    def cancel_reminder(self, user_id: int, reminder_id: str) -> bool:
        cursor = self.store.execute(
            "DELETE FROM reminders WHERE user_id = ? AND id = ? AND done_at IS NULL",
            (user_id, reminder_id),
        )
        return cursor.rowcount == 1

    # Everything, for "Delete my data" and "forget everything".

    def delete_user(self, user_id: int) -> dict[str, int]:
        counts = {}
        for table in ("observations", "networks", "learnings", "reminders"):
            cursor = self.store.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            counts[table] = cursor.rowcount
        return counts
