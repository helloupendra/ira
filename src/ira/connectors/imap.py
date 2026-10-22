"""Mail over IMAP, read-only, with an app password: Gmail, Outlook, Zoho or any mail host.

No Google verification is needed: the person makes an app password at their
mail provider (Gmail: Google Account, Security, 2-Step Verification, App
passwords) and Ira reads with it. The mailbox is always opened read-only, so
reading never marks a message as read.
"""

from __future__ import annotations

import asyncio
import email
import email.policy
import html
import imaplib
import re
import ssl
from email.message import EmailMessage
from typing import Any

from ira.tools.registry import ToolError

MAX_BODY = 20_000
TIMEOUT = 30

TOOLS: list[dict[str, Any]] = [
    {
        "mcp_name": "mail_search",
        "description": "Search the person's mail (IMAP) for words, a sender or a subject, newest "
        "first: sender, subject, date and an id for mail_read.",
        "schema": {
            "type": "object",
            "properties": {
                "words": {"type": "string", "description": "Words anywhere in the mail."},
                "sender": {"type": "string"},
                "subject": {"type": "string"},
                "days": {"type": "integer", "minimum": 1, "maximum": 365},
                "max": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        },
    },
    {
        "mcp_name": "mail_read",
        "description": "Read one mail by its id from mail_search: sender, subject, date, text.",
        "schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
]


def _quote(text: str) -> str:
    clean = re.sub(r'["\\\r\n]', " ", text).strip()[:100]
    return f'"{clean}"'


def criteria(args: dict[str, Any]) -> list[str]:
    import datetime as dt

    parts: list[str] = []
    if args.get("words"):
        parts += ["TEXT", _quote(str(args["words"]))]
    if args.get("sender"):
        parts += ["FROM", _quote(str(args["sender"]))]
    if args.get("subject"):
        parts += ["SUBJECT", _quote(str(args["subject"]))]
    days = int(args.get("days") or 30)
    since = dt.date.today() - dt.timedelta(days=max(1, min(days, 365)))
    parts += ["SINCE", since.strftime("%d-%b-%Y")]
    return parts


def _text(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = part.get_content()
    if part.get_content_subtype() == "html":
        content = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", content, flags=re.S | re.I)
        content = html.unescape(re.sub(r"<[^>]+>", " ", content))
    return re.sub(r"\n\s*\n+", "\n\n", content).strip()


class Mailbox:
    def __init__(self, host: str, user: str, password: str, port: int = 993) -> None:
        self.host, self.user, self.password, self.port = host, user, password, port

    def _open(self) -> imaplib.IMAP4_SSL:
        try:
            box = imaplib.IMAP4_SSL(
                self.host, self.port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT
            )
            box.login(self.user, self.password)
            box.select("INBOX", readonly=True)  # reading never marks anything as read
        except imaplib.IMAP4.error:
            raise ToolError("the mail server refused that address or app password") from None
        except OSError as exc:
            raise ToolError(f"could not reach {self.host} ({type(exc).__name__})") from None
        return box

    def _search(self, args: dict[str, Any]) -> dict[str, Any]:
        box = self._open()
        try:
            status, data = box.uid("SEARCH", None, *criteria(args))
            if status != "OK":
                raise ToolError("the mail server could not search")
            uids = (data[0] or b"").split()[::-1][: int(args.get("max") or 10)]
            found = []
            for uid in uids:
                status, parts = box.uid(
                    "FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
                )
                raw = next((p[1] for p in parts if isinstance(p, tuple)), b"")
                headers = email.message_from_bytes(raw, policy=email.policy.default)
                found.append(
                    {
                        "id": uid.decode(),
                        "from": str(headers.get("from", "")),
                        "subject": str(headers.get("subject", "")),
                        "date": str(headers.get("date", "")),
                    }
                )
            return {"messages": found}
        finally:
            _close(box)

    def _read(self, uid: str) -> dict[str, Any]:
        if not re.fullmatch(r"\d{1,12}", uid):
            raise ToolError("that is not a mail id from mail_search")
        box = self._open()
        try:
            status, parts = box.uid("FETCH", uid, "(BODY.PEEK[])")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            if status != "OK" or raw is None:
                raise ToolError("no such mail")
            message = email.message_from_bytes(raw, policy=email.policy.default)
            assert isinstance(message, EmailMessage)
            return {
                "from": str(message.get("from", "")),
                "to": str(message.get("to", "")),
                "subject": str(message.get("subject", "")),
                "date": str(message.get("date", "")),
                "text": _text(message)[:MAX_BODY],
            }
        finally:
            _close(box)

    def check(self) -> None:
        _close(self._open())

    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "mail_search":
            return await asyncio.to_thread(self._search, args)
        if name == "mail_read":
            return await asyncio.to_thread(self._read, str(args.get("id", "")))
        raise ToolError(f"no tool {name}")


def _close(box: imaplib.IMAP4_SSL) -> None:
    try:
        box.logout()
    except (imaplib.IMAP4.error, OSError):
        pass
