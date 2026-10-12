"""Conversation history, kept in SQLite so it survives restarts and the admin can read it."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from ira.models.base import Message, ToolCall
from ira.store import Store


def _encode(message: Message) -> tuple[str | None, str | None]:
    content = message.content
    if isinstance(content, list):
        content = json.dumps(content)
    calls = (
        json.dumps(
            [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in message.tool_calls]
        )
        if message.tool_calls
        else None
    )
    return content, calls


def _decode(row: Any) -> Message:
    calls = [ToolCall(**c) for c in json.loads(row["tool_calls"])] if row["tool_calls"] else []
    return Message(
        role=row["role"],
        content=row["content"],
        tool_calls=calls,
        tool_call_id=row["tool_call_id"],
        name=row["name"],
    )


class Conversations:
    def __init__(self, store: Store, *, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.clock = clock

    def ensure(self, conversation_id: str, *, channel: str, user_id: int | None) -> None:
        now = self.clock()
        self.store.execute(
            "INSERT OR IGNORE INTO conversations (id, channel, user_id, started_at, last_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (conversation_id, channel, user_id, now, now),
        )

    def owner(self, conversation_id: str) -> int | None:
        row = self.store.one("SELECT user_id FROM conversations WHERE id = ?", (conversation_id,))
        return row["user_id"] if row else None

    def exists(self, conversation_id: str) -> bool:
        return (
            self.store.one("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,))
            is not None
        )

    def append(self, conversation_id: str, messages: list[Message]) -> None:
        now = self.clock()
        for message in messages:
            content, calls = _encode(message)
            self.store.execute(
                "INSERT INTO messages (conversation_id, at, role, content, tool_calls, "
                "tool_call_id, name, action_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    conversation_id,
                    now,
                    message.role,
                    content,
                    calls,
                    message.tool_call_id,
                    message.name,
                    message.action_id,
                ),
            )
        turns = sum(1 for m in messages if m.role == "user")
        self.store.execute(
            "UPDATE conversations SET last_at = ?, turns = turns + ? WHERE id = ?",
            (now, turns, conversation_id),
        )

    def load(self, conversation_id: str, limit: int) -> list[Message]:
        """The latest ``limit`` messages since the last reset, starting at a user turn.

        A window must not open on a tool result or a tool-calling turn: providers
        reject a tool result whose call has been cut off.
        """
        rows = self.store.query(
            "SELECT m.* FROM messages m JOIN conversations c ON c.id = m.conversation_id "
            "WHERE m.conversation_id = ? AND m.at >= c.reset_at ORDER BY m.id DESC LIMIT ?",
            (conversation_id, limit),
        )
        messages = [_decode(r) for r in reversed(rows)]
        while messages and messages[0].role != "user":
            messages.pop(0)
        return messages

    def reset(self, conversation_id: str) -> None:
        """Start fresh context; the transcript stays for the admin."""
        self.store.execute(
            "UPDATE conversations SET reset_at = ? WHERE id = ?", (self.clock(), conversation_id)
        )

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        """One conversation's row, as ``recent`` returns them."""
        rows = self._rows(["c.id = ?"], [conversation_id], 1)
        return rows[0] if rows else None

    def recent(
        self,
        limit: int = 50,
        before: float | None = None,
        *,
        before_id: str | None = None,
        user_id: int | None = None,
        prefix: str = "",
    ) -> list[dict[str, Any]]:
        """Conversations by last activity, newest first (ties by id, highest first).

        Page with the last row's ``last_at`` as ``before`` and its id as
        ``before_id``: rows that share a ``last_at`` are then neither skipped
        nor repeated. ``before`` alone keeps only strictly older rows.
        ``user_id`` keeps one user's; ``prefix`` keeps ids that start with it.
        """
        where: list[str] = []
        params: list[Any] = []
        if before is not None and before_id is not None:
            where.append("(c.last_at < ? OR (c.last_at = ? AND c.id < ?))")
            params += [before, before, before_id]
        elif before is not None:
            where.append("c.last_at < ?")
            params.append(before)
        if user_id is not None:
            where.append("c.user_id = ?")
            params.append(user_id)
        if prefix:
            where.append("substr(c.id, 1, ?) = ?")
            params += [len(prefix), prefix]
        return self._rows(where, params, limit)

    def _rows(self, where: list[str], params: list[Any], limit: int) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT c.*, u.email, (SELECT substr(m.content, 1, 120) FROM messages m "
            "WHERE m.conversation_id = c.id AND m.role = 'user' ORDER BY m.id LIMIT 1) AS preview "
            "FROM conversations c LEFT JOIN users u ON u.id = c.user_id "
            f"WHERE {' AND '.join(where) or '1'} ORDER BY c.last_at DESC, c.id DESC LIMIT ?",
            (*params, limit),
        )
        return [dict(r) for r in rows]

    def transcript(self, conversation_id: str) -> list[dict[str, Any]]:
        """Every message, oldest first. A tool result that proposed an action carries
        that action as it stands now (expire overdue actions before calling this)."""
        rows = self.store.query(
            "SELECT m.id, m.at, m.role, m.content, m.tool_calls, m.tool_call_id, m.name, "
            "a.id AS action_id, a.tool AS action_tool, a.summary AS action_summary, "
            "a.status AS action_status, a.expires_at AS action_expires_at "
            "FROM messages m LEFT JOIN pending_actions a ON a.id = m.action_id "
            "WHERE m.conversation_id = ? ORDER BY m.id",
            (conversation_id,),
        )
        out = []
        for row in rows:
            item = {k: row[k] for k in ("id", "at", "role", "content", "tool_call_id", "name")}
            item["tool_calls"] = json.loads(row["tool_calls"]) if row["tool_calls"] else []
            item["action"] = (
                {
                    "id": row["action_id"],
                    "tool": row["action_tool"],
                    "summary": row["action_summary"],
                    "status": row["action_status"],
                    "expires_at": row["action_expires_at"],
                }
                if row["action_id"]
                else None
            )
            out.append(item)
        return out
