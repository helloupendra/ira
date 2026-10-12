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
                "tool_call_id, name) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    conversation_id,
                    now,
                    message.role,
                    content,
                    calls,
                    message.tool_call_id,
                    message.name,
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

    def recent(self, limit: int = 50, before: float | None = None) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT c.*, u.email, (SELECT substr(m.content, 1, 120) FROM messages m "
            "WHERE m.conversation_id = c.id AND m.role = 'user' ORDER BY m.id LIMIT 1) AS preview "
            "FROM conversations c LEFT JOIN users u ON u.id = c.user_id "
            "WHERE c.last_at < ? ORDER BY c.last_at DESC LIMIT ?",
            (before if before is not None else float("inf"), limit),
        )
        return [dict(r) for r in rows]

    def transcript(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT id, at, role, content, tool_calls, tool_call_id, name FROM messages "
            "WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        )
        out = []
        for row in rows:
            item = dict(row)
            item["tool_calls"] = json.loads(row["tool_calls"]) if row["tool_calls"] else []
            out.append(item)
        return out
