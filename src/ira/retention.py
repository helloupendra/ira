"""Keep the logs that only grow to the days set under ``retention`` in ira.yaml.

Only what nobody was promised is deleted on its own: live calls' timings by default; the
cost log, "What Ira did", the audit log and the change log only when the owner sets days
for them; sessions once they ended, and invites and pairing codes that were never used.
Conversations, Drop, devices, reminders and a business's actions have their own rules and
are never touched here. Rows go a thousand at a time, so live calls never wait long.
"""

from __future__ import annotations

import logging
import time

from ira.config import RetentionConfig
from ira.store import Store

log = logging.getLogger("ira.retention")

BATCH = 1000
DAY = 86400


def clean(store: Store, config: RetentionConfig, now: float | None = None) -> dict[str, int]:
    """Delete what is past its days. Returns how many rows went from each table."""
    now = time.time() if now is None else now
    deleted: dict[str, int] = {}

    def drop(table: str, where: str, params: tuple[float, ...]) -> None:
        total = 0
        while True:
            cursor = store.execute(
                f"DELETE FROM {table} WHERE rowid IN "
                f"(SELECT rowid FROM {table} WHERE {where} LIMIT {BATCH})",
                params,
            )
            total += cursor.rowcount
            if cursor.rowcount < BATCH:
                break
        if total:
            deleted[table] = total

    for table, days in (
        ("calls", config.calls_days),
        ("voice_turns", config.voice_days),
        ("tool_log", config.tool_log_days),
        ("audit_log", config.audit_days),
        ("change_log", config.change_log_days),
    ):
        if days is not None:
            drop(table, "at < ?", (now - days * DAY,))

    ended = now - config.ended_days * DAY
    drop("sessions", "revoked_at < ? OR expires_at < ?", (ended, ended))
    # Used invites and pairings stay: they say who brought in whom, and which code paired a device.
    drop("invites", "used_at IS NULL AND (revoked_at < ? OR expires_at < ?)", (ended, ended))
    drop("device_pairings", "used_at IS NULL AND expires_at < ?", (ended,))
    drop("pairing_codes", "used_at < ? OR expires_at < ?", (ended, ended))
    if deleted:
        log.info("retention: %s", ", ".join(f"{n} from {t}" for t, n in sorted(deleted.items())))
    return deleted
