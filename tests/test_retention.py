"""The logs that only grow are kept to their days; what a person or business is promised
stays; and the admin pages read without holding the lock live calls write through."""

from __future__ import annotations

import threading

from ira.config import RetentionConfig
from ira.retention import clean
from ira.store import Store

NOW = 2_000_000_000.0
DAY = 86400


def rows(store: Store, table: str) -> int:
    return store.one(f"SELECT COUNT(*) AS n FROM {table}")["n"]


def log_rows(store: Store, at: float) -> None:
    store.execute(
        "INSERT INTO calls (at, tier, purpose, tried, attempts, ok, seconds) "
        "VALUES (?, 'default', 'chat', 'm', 1, 1, 0.1)",
        (at,),
    )
    store.execute("INSERT INTO voice_turns (user_id, at) VALUES (1, ?)", (at,))
    store.execute(
        "INSERT INTO tool_log (at, tool, tier, outcome) VALUES (?, 'files_find', 0, 'ok')", (at,)
    )
    store.execute("INSERT INTO audit_log (at, outcome) VALUES (?, 'executed')", (at,))
    store.execute("INSERT INTO change_log (at, actor, what) VALUES (?, 'owner', 'x')", (at,))


def test_only_what_nobody_was_promised_goes_by_default(tmp_path):
    store = Store(tmp_path / "ira.db")
    log_rows(store, NOW - 400 * DAY)
    log_rows(store, NOW - DAY)
    deleted = clean(store, RetentionConfig(), now=NOW)
    assert deleted == {"calls": 1, "voice_turns": 1}
    for kept in ("tool_log", "audit_log", "change_log"):
        assert rows(store, kept) == 2, kept

    owner_chose = RetentionConfig(tool_log_days=365, audit_days=365, change_log_days=365)
    assert clean(store, owner_chose, now=NOW) == {"tool_log": 1, "audit_log": 1, "change_log": 1}
    assert rows(store, "calls") == rows(store, "audit_log") == 1


def test_ended_sessions_and_unused_codes_go_and_the_rest_stays(tmp_path):
    store = Store(tmp_path / "ira.db")
    store.execute(
        "INSERT INTO users (email, password_hash, role, created_at) "
        "VALUES ('owner@example.com', 'x', 'owner', 1)"
    )
    sessions = [
        ("old", NOW - 40 * DAY, None),  # expired long ago
        ("out", NOW + DAY, NOW - 40 * DAY),  # signed out long ago
        ("live", NOW + DAY, None),
        ("just", NOW - DAY, None),  # expired yesterday: kept a while yet
    ]
    for sid, expires, revoked in sessions:
        store.execute(
            "INSERT INTO sessions (id, token_hash, user_id, created_at, expires_at, revoked_at) "
            "VALUES (?, ?, 1, 1, ?, ?)",
            (sid, sid, expires, revoked),
        )
    for iid, used in (("unused", None), ("used", NOW - 100 * DAY)):
        store.execute(
            "INSERT INTO invites (id, token_hash, email, role, created_by, created_at, expires_at, "
            "used_at) VALUES (?, ?, 'a@example.com', 'staff', 'owner', 1, ?, ?)",
            (iid, iid, NOW - 60 * DAY, used),
        )
    clean(store, RetentionConfig(), now=NOW)
    assert {r["id"] for r in store.query("SELECT id FROM sessions")} == {"live", "just"}
    assert [r["id"] for r in store.query("SELECT id FROM invites")] == ["used"]


def test_many_rows_go_a_batch_at_a_time(tmp_path):
    store = Store(tmp_path / "ira.db")
    for _ in range(2500):
        store.execute(
            "INSERT INTO calls (at, tier, purpose, tried, attempts, ok, seconds) "
            "VALUES (1, 'default', 'chat', 'm', 1, 1, 0.1)"
        )
    assert clean(store, RetentionConfig(), now=NOW)["calls"] == 2500 and rows(store, "calls") == 0


def test_the_admin_pages_read_while_a_write_holds_the_lock(tmp_path):
    store = Store(tmp_path / "ira.db")
    log_rows(store, NOW)
    holding, release = threading.Event(), threading.Event()

    def writer() -> None:
        with store._lock:
            holding.set()
            release.wait(5)

    thread = threading.Thread(target=writer)
    thread.start()
    holding.wait(5)
    try:
        assert store.read_one("SELECT COUNT(*) AS n FROM calls")["n"] == 1  # did not wait
    finally:
        release.set()
        thread.join()
    indexes = {
        r["name"] for r in store.query("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    assert {"calls_at", "audit_log_action", "messages_role_at", "tool_log_at"} <= indexes
