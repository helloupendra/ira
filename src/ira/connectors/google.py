"""Google: Gmail and Calendar, read-only, signed in by each person through the operator's
own Google OAuth client.

Scopes: ``gmail.readonly`` and ``calendar.readonly``, nothing more. Gmail's
scopes are "restricted": while the operator's app is in Testing (with each
person added as a test user), Google lets a sign-in last 7 days; a published
app needs Google's verification and possibly a security assessment. Mail can
also come in over IMAP with an app password instead (``imap.py``).

The operator sets ``connectors.google.client_id`` and the secret's variable
(``client_secret_env``, ``GOOGLE_CLIENT_SECRET`` by default), and adds this
server's ``/v1/connections/oauth/callback`` as a redirect URI.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import html
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

import httpx

from ira.tools.registry import ToolError

AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR = "https://www.googleapis.com/calendar/v3"
SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
)
MAX_BODY = 20_000

# Ira's tools for a Google connection: all Tier 0, all read-only.
TOOLS: list[dict[str, Any]] = [
    {
        "mcp_name": "mail_search",
        "description": "Search the person's Gmail with Gmail's own search words (from:, "
        "subject:, newer_than:2d, is:unread) and list matches: sender, subject, date, snippet.",
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search, such as from:bank"},
                "max": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        },
    },
    {
        "mcp_name": "mail_read",
        "description": "Read one Gmail message, by its id from mail_search: sender, subject, "
        "date and its text.",
        "schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "mcp_name": "calendar_events",
        "description": "The person's Google Calendar events between two dates (ISO, such as "
        "2026-10-23), from all their calendars, optionally matching words.",
        "schema": {
            "type": "object",
            "properties": {
                "start": {"type": "string", "description": "From this date or time."},
                "end": {"type": "string", "description": "Until this date or time."},
                "query": {"type": "string"},
            },
        },
    },
]


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.decode().rstrip("=")


class Google:
    def __init__(
        self, client_id: str, client_secret: str, http: httpx.AsyncClient | None = None
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = http or httpx.AsyncClient(timeout=30)

    def authorize_url(self, redirect_uri: str, state: str, challenge: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",  # a refresh token, so Ira can read when you are away
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{AUTHORIZE}?{urlencode(params)}"

    async def _token(self, form: dict[str, str]) -> dict[str, Any]:
        response = await self.http.post(TOKEN, data=form)
        if response.status_code != 200:
            reason = response.json().get("error", "") if response.content else ""
            raise ToolError(f"Google refused the sign-in ({reason or response.status_code})")
        data = response.json()
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token"),
            "expires_at": time.time() + float(data.get("expires_in", 3600)) - 60,
            "scope": data.get("scope", ""),
        }

    async def exchange(self, code: str, redirect_uri: str, verifier: str) -> dict[str, Any]:
        return await self._token(
            {
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            }
        )

    async def access(
        self, tokens: dict[str, Any], save: Callable[[dict[str, Any]], Awaitable[None] | None]
    ) -> str:
        """A live access token, refreshed (and saved) when it has expired."""
        if tokens.get("access_token") and time.time() < float(tokens.get("expires_at", 0)):
            return str(tokens["access_token"])
        if not tokens.get("refresh_token"):
            raise ToolError("Google wants you to sign in again")
        try:
            fresh = await self._token(
                {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": tokens["refresh_token"],
                    "grant_type": "refresh_token",
                }
            )
        except ToolError:
            raise ToolError("Google wants you to sign in again") from None
        fresh["refresh_token"] = fresh.get("refresh_token") or tokens["refresh_token"]
        tokens.update(fresh)
        result = save(tokens)
        if result is not None:
            await result
        return str(tokens["access_token"])

    async def get(self, url: str, token: str, params: dict[str, Any] | None = None) -> Any:
        response = await self.http.get(
            url, params=params, headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code == 401:
            raise ToolError("Google wants you to sign in again")
        if response.status_code != 200:
            raise ToolError(f"Google answered HTTP {response.status_code}")
        return response.json()

    # The tools.

    async def mail_search(self, token: str, query: str, limit: int) -> dict[str, Any]:
        listed = await self.get(
            f"{GMAIL}/messages", token, {"q": query or "in:inbox", "maxResults": limit}
        )
        found = []
        for item in (listed.get("messages") or [])[:limit]:
            message = await self.get(
                f"{GMAIL}/messages/{item['id']}",
                token,
                [("format", "metadata")]
                + [("metadataHeaders", h) for h in ("From", "Subject", "Date")],
            )
            headers = _headers(message)
            found.append(
                {
                    "id": message.get("id"),
                    "from": headers.get("from"),
                    "subject": headers.get("subject"),
                    "date": headers.get("date"),
                    "snippet": html.unescape(message.get("snippet", "")),
                    "unread": "UNREAD" in (message.get("labelIds") or []),
                }
            )
        return {"messages": found}

    async def mail_read(self, token: str, message_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", message_id):
            raise ToolError("that is not a message id from mail_search")
        message = await self.get(f"{GMAIL}/messages/{message_id}", token, {"format": "full"})
        headers = _headers(message)
        return {
            "from": headers.get("from"),
            "to": headers.get("to"),
            "subject": headers.get("subject"),
            "date": headers.get("date"),
            "text": _body(message.get("payload") or {})[:MAX_BODY],
        }

    async def calendar_events(
        self,
        token: str,
        start: str | None,
        end: str | None,
        query: str | None,
        zone: dt.tzinfo = dt.UTC,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"singleEvents": "true", "orderBy": "startTime", "maxResults": 50}
        if start:
            params["timeMin"] = _rfc3339(start, zone)
        if end:
            params["timeMax"] = _rfc3339(end, zone, end_of_day=True)
        if query:
            params["q"] = query
        calendars = await self.get(f"{CALENDAR}/users/me/calendarList", token)
        events = []
        for calendar in (calendars.get("items") or [])[:10]:
            listed = await self.get(f"{CALENDAR}/calendars/{calendar['id']}/events", token, params)
            for event in listed.get("items") or []:
                events.append(
                    {
                        "calendar": calendar.get("summary"),
                        "title": event.get("summary"),
                        "start": (event.get("start") or {}).get("dateTime")
                        or (event.get("start") or {}).get("date"),
                        "end": (event.get("end") or {}).get("dateTime")
                        or (event.get("end") or {}).get("date"),
                        "where": event.get("location"),
                    }
                )
        events.sort(key=lambda e: str(e["start"]))
        return {"events": events[:100]}


def _headers(message: dict[str, Any]) -> dict[str, str]:
    return {
        str(h.get("name", "")).lower(): str(h.get("value", ""))
        for h in (message.get("payload") or {}).get("headers") or []
    }


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def _body(part: dict[str, Any]) -> str:
    """A message's text: its text/plain part, else its HTML with the tags taken out."""
    plain, rich = [], []

    def walk(node: dict[str, Any]) -> None:
        mime = node.get("mimeType", "")
        data = (node.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            rich.append(_decode(data))
        for child in node.get("parts") or []:
            walk(child)

    walk(part)
    if plain:
        return "\n".join(plain).strip()
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", "\n".join(rich), flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", " ", text)).strip()


def _rfc3339(value: str, zone: dt.tzinfo, *, end_of_day: bool = False) -> str:
    """A date or local time as RFC 3339, in the person's own time zone."""
    value = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            day = dt.date.fromisoformat(value)
            at = dt.time(23, 59, 59) if end_of_day else dt.time(0, 0)
            return dt.datetime.combine(day, at, zone).isoformat()
        moment = dt.datetime.fromisoformat(value)
    except ValueError:
        raise ToolError("give dates as 2026-10-23, or 2026-10-23T09:00") from None
    return (moment if moment.tzinfo else moment.replace(tzinfo=zone)).isoformat()
