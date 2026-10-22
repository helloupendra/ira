"""Ira's own state in one SQLite file: settings, users, conversations, calls, actions.

A single connection guarded by a lock is plenty for a one-owner assistant and
keeps the code free of a database server. The schema is created on open, and
columns added since v0.1 are added to an older file in place.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

# v0.1 kept one action PIN for the whole installation under this key. From v0.2
# each user has their own; see Store.adopt_shared_pin.
SHARED_PIN_SETTING = "actions.pin_hash"
CONFIRMING_ROLES = ("owner", "admin", "staff")

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
    finished_at     REAL,
    tier            INTEGER, -- 2: a "yes" from the person who asked; 3 (or NULL): a PIN
    user_id         INTEGER, -- who asked
    device_id       INTEGER  -- a device's tool: runs on that device once confirmed
);
CREATE INDEX IF NOT EXISTS pending_actions_conversation
    ON pending_actions (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS pending_actions_status ON pending_actions (status, expires_at);

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
    disabled_at   REAL,
    pin_hash      TEXT,
    pin_set_at    REAL
);

-- One-time invitation links. Only the hash of the token is kept.
CREATE TABLE IF NOT EXISTS invites (
    id         TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    email      TEXT NOT NULL,
    role       TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used_at    REAL,
    revoked_at REAL
);

-- Changes made from the admin console: who, what, when, and before -> after.
CREATE TABLE IF NOT EXISTS change_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      REAL NOT NULL,
    actor   TEXT NOT NULL,
    what    TEXT NOT NULL,
    target  TEXT,
    before  TEXT,
    after   TEXT,
    channel TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    token_hash   TEXT NOT NULL UNIQUE,
    user_id      INTEGER NOT NULL REFERENCES users (id),
    created_at   REAL NOT NULL,
    expires_at   REAL NOT NULL,
    last_seen_at REAL,
    revoked_at   REAL,
    user_agent   TEXT
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
    name            TEXT,
    action_id       TEXT, -- a tool result that proposed an action: that action
    model           TEXT, -- an assistant message: the provider:model that wrote it
    private         INTEGER NOT NULL DEFAULT 0 -- a device's output: only its user sees it
);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages (conversation_id, id);

CREATE TABLE IF NOT EXISTS telegram_chats (
    chat_id   INTEGER PRIMARY KEY,
    user_id   INTEGER NOT NULL REFERENCES users (id),
    paired_at REAL NOT NULL,
    name      TEXT  -- the chat's name as Telegram gives it, for the console
);

-- A person's own devices (a Mac, an Android phone). Only the token's hash is kept.
CREATE TABLE IF NOT EXISTS devices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users (id),
    kind         TEXT NOT NULL CHECK (kind IN ('mac', 'android')),
    label        TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,
    created_at   REAL NOT NULL,
    last_seen_at REAL,
    revoked_at   REAL,
    version      TEXT,
    tools        TEXT NOT NULL DEFAULT '[]', -- JSON: the tools of its last hello
    skills       TEXT NOT NULL DEFAULT '[]'  -- JSON: the skills its user switched on
);
CREATE INDEX IF NOT EXISTS devices_user ON devices (user_id);

-- One-time codes a device exchanges for its token. Only the code's hash is kept.
CREATE TABLE IF NOT EXISTS device_pairings (
    id         TEXT PRIMARY KEY,
    code_hash  TEXT NOT NULL UNIQUE,
    user_id    INTEGER NOT NULL REFERENCES users (id),
    kind       TEXT NOT NULL,
    label      TEXT NOT NULL,
    skills     TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used_at    REAL,
    device_id  INTEGER
);

-- What a device announced (a watched tab finished): title and text, no markup.
CREATE TABLE IF NOT EXISTS device_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users (id),
    device_id INTEGER,
    at        REAL NOT NULL,
    event     TEXT NOT NULL,
    title     TEXT NOT NULL,
    text      TEXT NOT NULL,
    data      TEXT
);
CREATE INDEX IF NOT EXISTS device_events_user ON device_events (user_id, id);

-- "What Ira did": every tool call, without its arguments or results.
-- Approval windows: after a PIN on a screen-control action, more steps on that device run
-- without asking until expires_at (docs/security.md, "Approvals").
CREATE TABLE IF NOT EXISTS approval_windows (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    device_id  INTEGER NOT NULL,
    opened_at  REAL NOT NULL,
    expires_at REAL NOT NULL,
    opened_by  TEXT,
    steps      INTEGER NOT NULL DEFAULT 0,
    closed_at  REAL,
    closed_why TEXT
);
CREATE INDEX IF NOT EXISTS approval_windows_user ON approval_windows (user_id, device_id);

-- Each device's approval key: a public key whose private half only the person's
-- fingerprint or face unlocks, so it may confirm instead of the PIN.
CREATE TABLE IF NOT EXISTS approval_keys (
    device_id  INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    public_key TEXT NOT NULL,
    algorithm  TEXT NOT NULL,
    created_at REAL NOT NULL
);

-- The businesses a person works with, as they describe them: Ira keeps them in mind.
CREATE TABLE IF NOT EXISTS businesses (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    name       TEXT NOT NULL,
    about      TEXT NOT NULL DEFAULT '',
    people     TEXT NOT NULL DEFAULT '',
    terms      TEXT NOT NULL DEFAULT '',
    may_do     TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS businesses_name ON businesses (user_id, name COLLATE NOCASE);

-- Answers people reported (Play asks every AI app for this): which answer, why, when.
CREATE TABLE IF NOT EXISTS reports (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    reason     TEXT NOT NULL,
    note       TEXT,
    status     TEXT NOT NULL DEFAULT 'open',
    created_at REAL NOT NULL,
    closed_at  REAL,
    closed_by  TEXT
);
CREATE INDEX IF NOT EXISTS reports_created ON reports (created_at);

-- A person's connections to other services (MCP servers). The secret is sealed with
-- AES-GCM under a key kept outside this database; tools is the list last fetched.
CREATE TABLE IF NOT EXISTS connections (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    name       TEXT NOT NULL,
    slug       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    url        TEXT,
    server     TEXT,
    secret     BLOB,
    tools      TEXT NOT NULL DEFAULT '[]',
    enabled    INTEGER NOT NULL DEFAULT 1,
    status     TEXT NOT NULL DEFAULT 'new',
    error      TEXT,
    created_at REAL NOT NULL,
    checked_at REAL,
    UNIQUE (user_id, slug)
);

-- Real-time voice: each turn's timings, never its words. latency_ms is from the
-- end of the person's speech to the first word they heard, on the app's clock.
CREATE TABLE IF NOT EXISTS voice_turns (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    at             REAL NOT NULL,
    client         TEXT,
    latency_ms     REAL,
    stt_ms         REAL,
    model_first_ms REAL,
    tts_first_ms   REAL
);
CREATE INDEX IF NOT EXISTS voice_turns_at ON voice_turns (at);

CREATE TABLE IF NOT EXISTS tool_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    at              REAL NOT NULL,
    user_id         INTEGER,
    channel         TEXT,
    conversation_id TEXT,
    tool            TEXT NOT NULL,
    device_id       INTEGER,
    tier            INTEGER NOT NULL,
    outcome         TEXT NOT NULL,
    seconds         REAL
);
CREATE INDEX IF NOT EXISTS tool_log_user ON tool_log (user_id, id);

-- Each person's own preferences: the assistant's name, languages, skills.
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER NOT NULL REFERENCES users (id),
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

-- Learning (opt-in, per person): what was noticed, the networks they named, what
-- Ira learned from it, and their reminders. Place labels only, never coordinates.
CREATE TABLE IF NOT EXISTS observations (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users (id),
    at        REAL NOT NULL,
    kind      TEXT NOT NULL,
    label     TEXT,
    source    TEXT NOT NULL,
    device_id INTEGER,
    detail    TEXT
);
CREATE INDEX IF NOT EXISTS observations_user ON observations (user_id, at);

CREATE TABLE IF NOT EXISTS networks (
    user_id     INTEGER NOT NULL REFERENCES users (id),
    fingerprint TEXT NOT NULL, -- a salted hash made on the device; never a network's name
    device_id   INTEGER,
    label       TEXT,
    first_seen  REAL NOT NULL,
    last_seen   REAL NOT NULL,
    PRIMARY KEY (user_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS learnings (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users (id),
    kind       TEXT NOT NULL,
    key        TEXT NOT NULL,
    text       TEXT NOT NULL,
    evidence   TEXT NOT NULL,
    confidence REAL NOT NULL,
    status     TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    asked_at   REAL,
    decided_at REAL,
    UNIQUE (user_id, key)
);

CREATE TABLE IF NOT EXISTS reminders (
    id              TEXT PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users (id),
    text            TEXT NOT NULL,
    due_at          REAL,
    trigger         TEXT NOT NULL, -- time, arrive or leave
    place           TEXT,
    created_at      REAL NOT NULL,
    done_at         REAL,
    conversation_id TEXT
);
CREATE INDEX IF NOT EXISTS reminders_user ON reminders (user_id, done_at);

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
            self._add_missing_columns()
        self.adopt_shared_pin()

    # Columns added after v0.1: (table, column, declaration).
    _ADDED_COLUMNS = (
        ("users", "pin_hash", "TEXT"),
        ("users", "pin_set_at", "REAL"),
        ("sessions", "user_agent", "TEXT"),
        ("messages", "action_id", "TEXT"),
        ("change_log", "channel", "TEXT"),
        ("messages", "model", "TEXT"),
        ("telegram_chats", "name", "TEXT"),
        ("messages", "private", "INTEGER NOT NULL DEFAULT 0"),
        ("pending_actions", "tier", "INTEGER"),
        ("pending_actions", "user_id", "INTEGER"),
        ("pending_actions", "device_id", "INTEGER"),
        ("device_pairings", "uses_left", "INTEGER"),
    )

    def _add_missing_columns(self) -> None:
        added = set()
        for table, column, declaration in self._ADDED_COLUMNS:
            present = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            if column not in present:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
                added.add((table, column))
        if ("messages", "action_id") in added:
            self._link_old_proposals()

    def _link_old_proposals(self) -> None:
        """Point tool results stored before ``messages.action_id`` at the actions they proposed.

        A turn's messages are stored together with one ``at``, and the actions
        it proposed were created during that turn: after the conversation's
        previous turn was stored. Within a turn, proposals of one tool pair up
        in order. Anything that does not line up is left unlinked.
        """
        rows = self._conn.execute(
            "SELECT id, conversation_id, at, name FROM messages WHERE role = 'tool' "
            "AND content LIKE ? ORDER BY id",
            ('%"pending_confirmation"%',),
        ).fetchall()
        turns: dict[tuple[str, float, str], list[int]] = {}
        for row in rows:
            turns.setdefault((row["conversation_id"], row["at"], row["name"]), []).append(row["id"])
        for (conversation, at, tool), message_ids in turns.items():
            previous = self._conn.execute(
                "SELECT MAX(at) AS at FROM messages WHERE conversation_id = ? AND at < ?",
                (conversation, at),
            ).fetchone()["at"]
            actions = self._conn.execute(
                "SELECT id FROM pending_actions WHERE conversation_id = ? AND tool = ? "
                "AND created_at > ? AND created_at <= ? ORDER BY created_at, rowid",
                (conversation, tool, -1.0 if previous is None else previous, at),
            ).fetchall()
            if len(actions) < len(message_ids):
                continue
            # More actions than results: the extra, earlier ones came from a turn never stored.
            for message_id, action in zip(message_ids, actions[-len(message_ids) :], strict=True):
                self._conn.execute(
                    "UPDATE messages SET action_id = ? WHERE id = ?", (action["id"], message_id)
                )

    def adopt_shared_pin(self) -> int:
        """Give a v0.1 installation PIN to every user who could confirm with it.

        Everyone keeps the PIN they used before until they set their own, and
        the shared copy is then removed. Nothing happens until a user exists.
        """
        with self.transaction():
            row = self.one("SELECT value FROM settings WHERE key = ?", (SHARED_PIN_SETTING,))
            users = self.one("SELECT COUNT(*) AS n FROM users WHERE disabled_at IS NULL")
            if row is None or not users or users["n"] == 0:
                return 0
            marks = ",".join("?" for _ in CONFIRMING_ROLES)
            cursor = self.execute(
                "UPDATE users SET pin_hash = ?, pin_set_at = ? "
                f"WHERE pin_hash IS NULL AND disabled_at IS NULL AND role IN ({marks})",
                (row["value"], time.time(), *CONFIRMING_ROLES),
            )
            self.execute("DELETE FROM settings WHERE key = ?", (SHARED_PIN_SETTING,))
            return cursor.rowcount

    @contextlib.contextmanager
    def transaction(self) -> Iterator[Store]:
        """Run several statements as one: all or nothing, and no other writer in between.

        ``BEGIN IMMEDIATE`` takes the write lock at once, so a check followed by
        a write ("no users yet" -> create the owner) cannot race another
        process on the same file. Transactions do not nest.
        """
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

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

    def delete_setting(self, key: str) -> None:
        self.execute("DELETE FROM settings WHERE key = ?", (key,))

    def close(self) -> None:
        with self._lock:
            self._conn.close()
