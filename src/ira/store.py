"""Ira's own state in one SQLite file: settings, users, conversations, calls, actions.

A single connection guarded by a lock is plenty for a one-owner assistant and
keeps the code free of a database server. The schema is created on open.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per gateway request. Never the API key or the prompt.
CREATE TABLE IF NOT EXISTS calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    at            REAL NOT NULL,
    tier          TEXT NOT NULL,
    purpose       TEXT NOT NULL,
    model         TEXT,
    tried         TEXT NOT NULL,
    attempts      INTEGER NOT NULL,
    ok            INTEGER NOT NULL,
    error_kind    TEXT,
    seconds       REAL NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL
);

CREATE TABLE IF NOT EXISTS pending_actions (
    id              TEXT PRIMARY KEY,
    tool            TEXT NOT NULL,
    params          TEXT NOT NULL,
    summary         TEXT NOT NULL,
    conversation_id TEXT,
    channel         TEXT,
    actor           TEXT,
    created_at      REAL NOT NULL,
    expires_at      REAL NOT NULL,
    status          TEXT NOT NULL,
    result          TEXT,
    finished_at     REAL
);
CREATE INDEX IF NOT EXISTS pending_actions_conversation
    ON pending_actions (conversation_id, created_at);

CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        REAL NOT NULL,
    action_id TEXT,
    tool      TEXT,
    outcome   TEXT NOT NULL,
    actor     TEXT,
    channel   TEXT,
    detail    TEXT
);

CREATE TABLE IF NOT EXISTS pin_state (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    failures     INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO pin_state (id, failures, locked_until) VALUES (1, 0, 0);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'staff', 'viewer')),
    created_at    REAL NOT NULL,
    last_login_at REAL,
    disabled_at   REAL
);

CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    token_hash   TEXT NOT NULL UNIQUE,
    user_id      INTEGER NOT NULL REFERENCES users (id),
    created_at   REAL NOT NULL,
    expires_at   REAL NOT NULL,
    last_seen_at REAL,
    revoked_at   REAL
);

-- API tokens belong to a user; their scopes can only narrow the user's role.
CREATE TABLE IF NOT EXISTS api_tokens (
    id           TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users (id),
    label        TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,
    scopes       TEXT NOT NULL,
    created_at   REAL NOT NULL,
    last_used_at REAL,
    revoked_at   REAL
);

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    channel    TEXT NOT NULL,
    user_id    INTEGER,
    started_at REAL NOT NULL,
    last_at    REAL NOT NULL,
    turns      INTEGER NOT NULL DEFAULT 0,
    reset_at   REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS conversations_last ON conversations (last_at);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations (id),
    at              REAL NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT,
    tool_calls      TEXT,
    tool_call_id    TEXT,
    name            TEXT
);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages (conversation_id, id);

CREATE TABLE IF NOT EXISTS telegram_chats (
    chat_id   INTEGER PRIMARY KEY,
    user_id   INTEGER NOT NULL REFERENCES users (id),
    paired_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS pairing_codes (
    code_hash  TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users (id),
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used_at    REAL,
    chat_id    INTEGER
);
"""


class Store:
    """Thread-safe helpers over one SQLite connection. ``":memory:"`` works for tests."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, tuple(params))

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchone()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
