"""Telegram as the person: a user client (MTProto, with Telethon), opt-in.

The bot (``channels.telegram``) is for talking to Ira. This is different: Ira
reads the person's own chats and, after their yes, sends as them. It needs
the person's own ``api_id`` and ``api_hash`` from my.telegram.org and their
own login (a code Telegram sends them, and their two-step password if set).
The session that results is sealed like any token.

Telegram allows user clients made with your own api_id. Heavy automation can
get an account limited, so Ira reads only when asked and sends one message
at a time, each read back and confirmed (Tier 2).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ira.tools.registry import ToolError

MAX_MESSAGES = 30
MAX_TEXT = 4000

TOOLS: list[dict[str, Any]] = [
    {
        "mcp_name": "chats",
        "description": "The person's recent Telegram chats: name, unread count, last message time.",
        "schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}},
        },
        "tier": 0,
    },
    {
        "mcp_name": "read",
        "description": "Read the latest messages of one Telegram chat, by its name as listed by "
        "chats: sender, time and text.",
        "schema": {
            "type": "object",
            "properties": {
                "chat": {"type": "string", "description": "The chat's name, or part of it."},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_MESSAGES},
            },
            "required": ["chat"],
        },
        "tier": 0,
    },
    {
        "mcp_name": "send",
        "description": "Send a Telegram message as the person to one chat, by its exact name. "
        "Read back the chat and the words; it waits for their yes.",
        "schema": {
            "type": "object",
            "properties": {
                "chat": {"type": "string", "description": "The chat's exact name."},
                "text": {"type": "string"},
            },
            "required": ["chat", "text"],
        },
        "tier": 2,
    },
]


class NeedsPassword(ToolError):
    """The account has two-step verification: its password is needed too."""


def _client(api_id: int, api_hash: str, session: str) -> Any:
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError as exc:  # pragma: no cover - only without the extra
        raise ToolError('Telegram needs: pip install "ira-assistant[connectors]"') from exc
    return TelegramClient(
        StringSession(session), api_id, api_hash, device_model="Ira", app_version="ira"
    )


def _name(entity: Any) -> str:
    title = getattr(entity, "title", None)
    if title:
        return str(title)
    parts = [getattr(entity, "first_name", None), getattr(entity, "last_name", None)]
    return " ".join(p for p in parts if p) or str(getattr(entity, "username", "") or "someone")


class TelegramUser:
    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session: str = "",
        client_factory: Callable[[int, str, str], Any] | None = None,
    ) -> None:
        self.api_id, self.api_hash = api_id, api_hash
        self.client = (client_factory or _client)(api_id, api_hash, session)
        self.connected = False

    async def _ready(self) -> Any:
        if not self.connected:
            await self.client.connect()
            self.connected = True
        return self.client

    async def close(self) -> None:
        if self.connected:
            result = self.client.disconnect()
            if hasattr(result, "__await__"):
                await result
            self.connected = False

    # Login.

    async def send_code(self, phone: str) -> str:
        client = await self._ready()
        try:
            sent = await client.send_code_request(phone)
        except Exception as exc:
            raise ToolError(f"Telegram did not send a code ({type(exc).__name__})") from None
        return str(sent.phone_code_hash)

    async def sign_in(self, phone: str, code: str, code_hash: str, password: str | None) -> str:
        """The session, once Telegram accepts the code (and the password, if it asks)."""
        from telethon.errors import (
            PasswordHashInvalidError,
            PhoneCodeExpiredError,
            PhoneCodeInvalidError,
            SessionPasswordNeededError,
        )

        client = await self._ready()
        try:
            if not await client.is_user_authorized():
                await client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
        except SessionPasswordNeededError:
            if not password:
                raise NeedsPassword("this account has a two-step password: give it too") from None
            try:
                await client.sign_in(password=password)
            except PasswordHashInvalidError:
                raise ToolError("that two-step password is wrong") from None
        except PhoneCodeInvalidError:
            raise ToolError("that code is wrong") from None
        except PhoneCodeExpiredError:
            raise ToolError("that code has expired: start again for a new one") from None
        return str(client.session.save())

    # The tools.

    async def _dialogs(self, limit: int) -> list[Any]:
        client = await self._ready()
        return [d async for d in client.iter_dialogs(limit=limit)]

    async def resolve(self, chat: str) -> Any:
        wanted = " ".join(chat.lower().split())
        if not wanted:
            raise ToolError("say which chat")
        dialogs = await self._dialogs(200)
        exact = [d for d in dialogs if _name(d.entity).lower() == wanted]
        if len(exact) == 1:
            return exact[0]
        close = exact or [d for d in dialogs if wanted in _name(d.entity).lower()]
        if not close:
            raise ToolError(f"no chat called {chat}")
        if len(close) > 1:
            names = ", ".join(sorted({_name(d.entity) for d in close})[:6])
            raise ToolError(f"several chats match {chat}: {names}. Which one?")
        return close[0]

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        if name == "chats":
            limit = max(1, min(int(args.get("limit") or 20), 50))
            return {
                "chats": [
                    {
                        "name": _name(d.entity),
                        "unread": int(getattr(d, "unread_count", 0) or 0),
                        "last": str(getattr(getattr(d, "message", None), "date", "") or ""),
                    }
                    for d in await self._dialogs(limit)
                ]
            }
        if name == "read":
            dialog = await self.resolve(str(args.get("chat") or ""))
            limit = max(1, min(int(args.get("limit") or 15), MAX_MESSAGES))
            client = await self._ready()
            messages = []
            async for message in client.iter_messages(dialog.entity, limit=limit):
                sender = getattr(message, "sender", None)
                messages.append(
                    {
                        "from": "you"
                        if getattr(message, "out", False)
                        else _name(sender or dialog.entity),
                        "at": str(getattr(message, "date", "")),
                        "text": str(getattr(message, "message", "") or "")[:MAX_TEXT],
                    }
                )
            return {"chat": _name(dialog.entity), "messages": messages[::-1]}
        if name == "send":
            text = str(args.get("text") or "").strip()
            if not text:
                raise ToolError("say what to send")
            if len(text) > MAX_TEXT:
                raise ToolError(f"keep the message under {MAX_TEXT} characters")
            chat = str(args.get("chat") or "")
            dialog = await self.resolve(chat)
            if re.sub(r"\s+", " ", _name(dialog.entity).lower()) != " ".join(chat.lower().split()):
                raise ToolError(f"send needs the chat's exact name: {_name(dialog.entity)}?")
            client = await self._ready()
            await client.send_message(dialog.entity, text)
            return {"summary": f"Sent to {_name(dialog.entity)}: {text}"}
        raise ToolError(f"no tool {name}")
