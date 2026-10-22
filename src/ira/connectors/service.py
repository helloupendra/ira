"""Each person's connections: kept, refreshed, offered as their tools, and called."""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ira.config import ConnectorsConfig
from ira.connectors import mcp
from ira.connectors.sealed import Sealer
from ira.store import Store
from ira.tools.personal import PersonalTool
from ira.tools.registry import ToolError

SLUG = re.compile(r"[^a-z0-9]+")


class ConnectionError_(ToolError):
    pass


class NeedsSignIn(ConnectionError_):
    """The service wants its sign-in again, and nobody is there to do it."""


SIGN_IN_SECONDS = 600.0  # the person has ten minutes to finish signing in


@dataclass
class GoogleSignIn:
    """A Google sign-in in progress: the PKCE verifier waits for the code."""

    connection_id: str
    user_id: int
    verifier: str
    redirect_uri: str


@dataclass
class SignIn:
    """One OAuth sign-in in progress: the address to open, then the code that comes back."""

    connection_id: str
    user_id: int
    url: asyncio.Future[str]
    code: asyncio.Future[Any]
    task: asyncio.Task[Any] | None = None


@dataclass
class Connection:
    id: str
    user_id: int
    name: str
    slug: str
    kind: str  # "mcp_http", "mcp_stdio", "google", "imap" or "telegram"
    url: str | None
    server: str | None
    tools: list[dict[str, Any]] = field(default_factory=list)
    enabled: bool = True
    status: str = "new"
    error: str | None = None
    created_at: float = 0.0
    checked_at: float | None = None

    def public(self) -> dict[str, Any]:
        """What the person sees: never the secret."""
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "kind": self.kind,
            "url": self.url,
            "server": self.server,
            "enabled": self.enabled,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
            "checked_at": self.checked_at,
            "tools": [
                {
                    k: t.get(k)
                    for k in ("name", "mcp_name", "description", "tier", "min_tier", "enabled")
                }
                for t in self.tools
            ],
        }


def _row(row: Any) -> Connection:
    return Connection(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        slug=row["slug"],
        kind=row["kind"],
        url=row["url"],
        server=row["server"],
        tools=json.loads(row["tools"] or "[]"),
        enabled=bool(row["enabled"]),
        status=row["status"],
        error=row["error"],
        created_at=row["created_at"],
        checked_at=row["checked_at"],
    )


def slug_for(name: str) -> str:
    slug = SLUG.sub("_", name.lower()).strip("_")[:20]
    return slug if slug and slug[0].isalpha() else f"c_{slug}"[:20]


class Connectors:
    def __init__(
        self,
        store: Store,
        sealer: Callable[[], Sealer],
        config: ConnectorsConfig,
        *,
        target_factory: Callable[[Connection, dict[str, Any]], Any] | None = None,
        callback_url: Callable[[], str] = lambda: "http://127.0.0.1:8765",
        google: Callable[[], Any] | None = None,
        mailbox: Callable[..., Any] | None = None,
        telegram: Callable[..., Any] | None = None,
        zone_for: Callable[[int], Any] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self._sealer = sealer
        self.config = config
        self._target_factory = target_factory
        self.clock = clock
        self.workers: dict[str, mcp.Worker] = {}
        # Where a service sends the browser back after sign-in (this server's own address).
        self.callback_url = callback_url
        self.sign_ins: dict[str, SignIn] = {}  # by connection
        self.by_state: dict[str, SignIn | GoogleSignIn] = {}  # by the state echoed back
        self._google = google
        self._mailbox = mailbox
        self._telegram = telegram
        self.telegrams: dict[str, Any] = {}  # live Telegram clients, by connection
        self.logins: dict[str, tuple[Any, str, str]] = {}  # (client, phone, code hash)
        self.zone_for = zone_for

    def sealer(self) -> Sealer:
        return self._sealer()

    # Reading.

    def for_user(self, user_id: int) -> list[Connection]:
        rows = self.store.query(
            "SELECT * FROM connections WHERE user_id = ? ORDER BY created_at", (user_id,)
        )
        return [_row(r) for r in rows]

    def get(self, user_id: int, connection_id: str) -> Connection:
        row = self.store.one(
            "SELECT * FROM connections WHERE id = ? AND user_id = ?", (connection_id, user_id)
        )
        if row is None:
            raise ConnectionError_("no such connection")
        return _row(row)

    def google(self) -> Any:
        """The operator's Google client, or None when this server offers no Google."""
        if self._google is not None:
            return self._google()
        import os

        from ira.connectors.google import Google

        cfg = self.config.google
        secret = os.environ.get(cfg.client_secret_env, "")
        return Google(cfg.client_id, secret) if cfg.client_id and secret else None

    def mailbox(self, host: str, user: str, password: str, port: int = 993) -> Any:
        if self._mailbox is not None:
            return self._mailbox(host, user, password, port)
        from ira.connectors.imap import Mailbox

        return Mailbox(host, user, password, port)

    def telegram(self, api_id: int, api_hash: str, session: str = "") -> Any:
        if self._telegram is not None:
            return self._telegram(api_id, api_hash, session)
        from ira.connectors.telegram_user import TelegramUser

        return TelegramUser(api_id, api_hash, session)

    def builtins(self) -> list[dict[str, Any]]:
        """Services Ira connects to itself, beside MCP servers."""
        try:
            import telethon  # noqa: F401

            telegram_ready = True
        except ImportError:
            telegram_ready = self._telegram is not None
        return [
            {
                "kind": "google",
                "name": "Google",
                "description": "Gmail and Google Calendar, read-only: you sign in with Google.",
                "available": self.google() is not None,
            },
            {
                "kind": "imap",
                "name": "Mail (IMAP)",
                "description": "Any mailbox, read-only, with an app password from your mail "
                "provider. No Google sign-in needed.",
                "available": True,
            },
            {
                "kind": "telegram",
                "name": "Telegram (as you)",
                "description": "Read your Telegram chats, and send as you after your yes. Needs "
                "your own api_id and api_hash from my.telegram.org.",
                "available": telegram_ready,
            },
        ]

    def servers(self) -> list[dict[str, Any]]:
        """The local MCP servers the operator allows, and what each person must give them."""
        return [
            {"name": name, "description": cfg.description, "needs": list(cfg.person_env)}
            for name, cfg in sorted(self.config.mcp_servers.items())
        ]

    # Adding and removing.

    def _secret(self, connection: Connection) -> dict[str, Any]:
        row = self.store.one("SELECT secret FROM connections WHERE id = ?", (connection.id,))
        blob = row["secret"] if row else None
        if not blob:
            return {}
        return self.sealer().open(bytes(blob), f"{connection.user_id}:{connection.id}")

    def _insert(
        self,
        user_id: int,
        name: str,
        kind: str,
        *,
        url: str | None,
        server: str | None,
        secret: dict[str, Any],
    ) -> Connection:
        name = " ".join(name.split())[:40]
        if not name:
            raise ConnectionError_("give the connection a name, such as GitHub")
        slug = slug_for(name)
        if self.store.one(
            "SELECT 1 FROM connections WHERE user_id = ? AND slug = ?", (user_id, slug)
        ):
            raise ConnectionError_(f"you already have a connection called {name}")
        connection_id = "con_" + secrets.token_hex(8)
        sealed = self.sealer().seal(secret, f"{user_id}:{connection_id}") if secret else None
        self.store.execute(
            "INSERT INTO connections (id, user_id, name, slug, kind, url, server, secret, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (connection_id, user_id, name, slug, kind, url, server, sealed, self.clock()),
        )
        return self.get(user_id, connection_id)

    def add_remote(
        self,
        user_id: int,
        name: str,
        url: str,
        headers: dict[str, str] | None = None,
        *,
        oauth: bool = False,
    ) -> Connection:
        url = mcp.check_url(url, self.config.allow_private)
        clean = {
            str(k).strip(): str(v).strip()
            for k, v in (headers or {}).items()
            if str(k).strip() and str(v).strip()
        }
        for key in clean:
            if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", key):
                raise ConnectionError_(f"'{key}' is not a header name")
        secret: dict[str, Any] = {"headers": clean}
        if oauth:
            secret["oauth"] = {}  # tokens come after the person signs in
        return self._insert(user_id, name, "mcp_http", url=url, server=None, secret=secret)

    def add_server(
        self, user_id: int, name: str, server: str, env: dict[str, str] | None = None
    ) -> Connection:
        cfg = self.config.mcp_servers.get(server)
        if cfg is None:
            raise ConnectionError_(f"this server offers no MCP server called {server}")
        given = {k: str(v) for k, v in (env or {}).items() if k in cfg.person_env and str(v)}
        missing = [k for k in cfg.person_env if k not in given]
        if missing:
            raise ConnectionError_(f"{server} needs {', '.join(missing)}")
        return self._insert(
            user_id, name or server, "mcp_stdio", url=None, server=server, secret={"env": given}
        )

    def _builtin_tools(self, slug: str, definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "name": mcp.tool_name(slug, d["mcp_name"]),
                "mcp_name": d["mcp_name"],
                "description": d["description"],
                "schema": d["schema"],
                "min_tier": int(d.get("tier", 0)),
                "tier": int(d.get("tier", 0)),
                "enabled": True,
            }
            for d in definitions
        ]

    def add_google(self, user_id: int, name: str = "Google") -> Connection:
        from ira.connectors.google import TOOLS

        if self.google() is None:
            raise ConnectionError_("this server offers no Google sign-in: its owner sets it up")
        connection = self._insert(user_id, name, "google", url=None, server=None, secret={})
        tools = self._builtin_tools(connection.slug, TOOLS)
        self.store.execute(
            "UPDATE connections SET tools = ?, status = 'needs_auth' WHERE id = ?",
            (json.dumps(tools), connection.id),
        )
        return self.get(user_id, connection.id)

    async def add_imap(
        self, user_id: int, name: str, host: str, user: str, password: str, port: int = 993
    ) -> Connection:
        from ira.connectors.imap import TOOLS

        host = host.strip()
        if not re.fullmatch(r"[A-Za-z0-9.-]{3,253}", host) or not user.strip() or not password:
            raise ConnectionError_("give the mail server, your address and an app password")
        mcp.check_url(f"https://{host}:{port}/", self.config.allow_private)
        await asyncio.to_thread(self.mailbox(host, user.strip(), password, port).check)
        connection = self._insert(
            user_id,
            name or "Mail",
            "imap",
            url=None,
            server=host,
            secret={"host": host, "port": port, "user": user.strip(), "password": password},
        )
        tools = self._builtin_tools(connection.slug, TOOLS)
        self.store.execute(
            "UPDATE connections SET tools = ?, status = 'ok' WHERE id = ?",
            (json.dumps(tools), connection.id),
        )
        return self.get(user_id, connection.id)

    async def add_telegram(
        self, user_id: int, name: str, api_id: int, api_hash: str, phone: str
    ) -> Connection:
        """Start signing in as the person: Telegram sends them a code."""
        from ira.connectors.telegram_user import TOOLS

        phone = re.sub(r"[\s()-]", "", phone)
        if not re.fullmatch(r"\+\d{7,15}", phone):
            raise ConnectionError_("give the phone number with its country code: +91...")
        if api_id <= 0 or not re.fullmatch(r"[0-9a-f]{32}", api_hash.strip().lower()):
            raise ConnectionError_("api_id and api_hash come from my.telegram.org, under API")
        client = self.telegram(api_id, api_hash.strip().lower())
        code_hash = await client.send_code(phone)
        connection = self._insert(
            user_id,
            name or "Telegram",
            "telegram",
            url=None,
            server=None,
            secret={"api_id": api_id, "api_hash": api_hash.strip().lower(), "phone": phone},
        )
        self.logins[connection.id] = (client, phone, code_hash)
        tools = self._builtin_tools(connection.slug, TOOLS)
        self.store.execute(
            "UPDATE connections SET tools = ?, status = 'needs_code' WHERE id = ?",
            (json.dumps(tools), connection.id),
        )
        return self.get(user_id, connection.id)

    async def telegram_code(
        self, user_id: int, connection_id: str, code: str, password: str | None = None
    ) -> Connection:
        """Finish signing in with the code Telegram sent (and the two-step password)."""
        from ira.connectors.telegram_user import NeedsPassword

        connection = self.get(user_id, connection_id)
        login = self.logins.get(connection.id)
        if login is None:
            raise ConnectionError_("this sign-in has expired: remove it and connect again")
        client, phone, code_hash = login
        try:
            session = await client.sign_in(phone, code.strip(), code_hash, password)
        except NeedsPassword:
            self.store.execute(
                "UPDATE connections SET status = 'needs_password' WHERE id = ?", (connection.id,)
            )
            raise
        secret = {**self._secret(connection), "session": session}
        sealed = self.sealer().seal(secret, f"{connection.user_id}:{connection.id}")
        self.store.execute(
            "UPDATE connections SET secret = ?, status = 'ok', error = NULL, checked_at = ? "
            "WHERE id = ?",
            (sealed, self.clock(), connection.id),
        )
        self.logins.pop(connection.id, None)
        self.telegrams[connection.id] = client
        return self.get(user_id, connection_id)

    async def remove(self, user_id: int, connection_id: str) -> None:
        connection = self.get(user_id, connection_id)
        for live in (
            self.telegrams.pop(connection.id, None),
            self.logins.pop(connection.id, (None,))[0],
        ):
            if live is not None:
                await live.close()
        worker = self.workers.pop(connection.id, None)
        if worker is not None:
            await worker.close()
        self.store.execute("DELETE FROM connections WHERE id = ?", (connection.id,))

    def delete_user(self, user_id: int) -> int:
        for connection in self.for_user(user_id):
            worker = self.workers.pop(connection.id, None)
            if worker is not None and worker.task is not None:
                worker.task.cancel()
        return self.store.execute("DELETE FROM connections WHERE user_id = ?", (user_id,)).rowcount

    # Changing.

    def set_enabled(self, user_id: int, connection_id: str, enabled: bool) -> Connection:
        connection = self.get(user_id, connection_id)
        self.store.execute(
            "UPDATE connections SET enabled = ? WHERE id = ?", (int(enabled), connection.id)
        )
        return self.get(user_id, connection_id)

    def set_tools(
        self, user_id: int, connection_id: str, changes: dict[str, dict[str, Any]]
    ) -> Connection:
        """Switch tools on or off, or raise a tool's tier. A tier never goes below its default."""
        connection = self.get(user_id, connection_id)
        tools = {t["name"]: t for t in connection.tools}
        for name, change in changes.items():
            tool = tools.get(name)
            if tool is None:
                raise ConnectionError_(f"{connection.name} has no tool {name}")
            if "enabled" in change and change["enabled"] is not None:
                tool["enabled"] = bool(change["enabled"])
            if change.get("tier") is not None:
                tier = int(change["tier"])
                if tier not in (0, 1, 2, 3):
                    raise ConnectionError_("a tier is 0, 1, 2 or 3")
                if tier < tool["min_tier"]:
                    raise ConnectionError_(
                        f"{name} can't go below Tier {tool['min_tier']}: its server marks it so"
                    )
                tool["tier"] = tier
        self.store.execute(
            "UPDATE connections SET tools = ? WHERE id = ?",
            (json.dumps(list(tools.values())), connection.id),
        )
        return self.get(user_id, connection_id)

    # The server.

    def _target(self, connection: Connection) -> Any:
        secret = self._secret(connection)
        if self._target_factory is not None:
            return self._target_factory(connection, secret)
        if connection.kind == "mcp_http":
            auth = self._oauth(connection) if "oauth" in secret else None
            return mcp.http_transport(str(connection.url), secret.get("headers") or {}, auth)
        cfg = self.config.mcp_servers.get(str(connection.server))
        if cfg is None:
            raise ConnectionError_(f"this server no longer offers {connection.server}")
        env = {**cfg.env, **(secret.get("env") or {})}
        return mcp.stdio_target(cfg.command, list(cfg.args), env)

    def _worker(self, connection: Connection) -> mcp.Worker:
        worker = self.workers.get(connection.id)
        if worker is None:
            worker = mcp.Worker(lambda: self._target(connection), connection.name)
            self.workers[connection.id] = worker
        return worker

    # OAuth: the SDK does discovery, registration, PKCE, the state check and the tokens;
    # here the person's browser goes to the service and comes back.

    def _seal_part(self, connection: Connection, key: str, value: Any) -> None:
        secret = self._secret(connection)
        secret.setdefault("oauth", {})[key] = value
        sealed = self.sealer().seal(secret, f"{connection.user_id}:{connection.id}")
        self.store.execute(
            "UPDATE connections SET secret = ? WHERE id = ?", (sealed, connection.id)
        )

    def _oauth(self, connection: Connection) -> Any:
        from mcp.client.auth import OAuthClientProvider, TokenStorage
        from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

        service = self

        class Sealed(TokenStorage):
            async def get_tokens(self) -> OAuthToken | None:
                saved = service._secret(connection).get("oauth", {}).get("tokens")
                return OAuthToken.model_validate(saved) if saved else None

            async def set_tokens(self, tokens: OAuthToken) -> None:
                service._seal_part(connection, "tokens", tokens.model_dump(mode="json"))

            async def get_client_info(self) -> OAuthClientInformationFull | None:
                saved = service._secret(connection).get("oauth", {}).get("client")
                return OAuthClientInformationFull.model_validate(saved) if saved else None

            async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
                service._seal_part(connection, "client", client_info.model_dump(mode="json"))

        async def redirect(url: str) -> None:
            sign_in = self.sign_ins.get(connection.id)
            if sign_in is None:
                raise NeedsSignIn(f"{connection.name} wants you to sign in again")
            state = (parse_qs(urlsplit(url).query).get("state") or [""])[0]
            self.by_state[state] = sign_in
            if not sign_in.url.done():
                sign_in.url.set_result(url)

        async def callback() -> Any:
            sign_in = self.sign_ins.get(connection.id)
            if sign_in is None:
                raise NeedsSignIn(f"{connection.name} wants you to sign in again")
            return await asyncio.wait_for(asyncio.shield(sign_in.code), SIGN_IN_SECONDS)

        metadata = OAuthClientMetadata(
            client_name="Ira",
            redirect_uris=[f"{self.callback_url().rstrip('/')}/v1/connections/oauth/callback"],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="none",
        )
        return OAuthClientProvider(
            server_url=str(connection.url),
            client_metadata=metadata,
            storage=Sealed(),
            redirect_handler=redirect,
            callback_handler=callback,
        )

    async def sign_in(self, user_id: int, connection_id: str) -> str | None:
        """Start signing in to a connection's service: the address to open, or None if it is
        already signed in. Signing in finishes in the background, when the browser comes back."""
        connection = self.get(user_id, connection_id)
        if connection.kind == "google":
            from ira.connectors.google import pkce

            google = self.google()
            if google is None:
                raise ConnectionError_("this server offers no Google sign-in")
            verifier, challenge = pkce()
            state = secrets.token_urlsafe(32)
            redirect = f"{self.callback_url().rstrip('/')}/v1/connections/oauth/callback"
            self.by_state[state] = GoogleSignIn(connection.id, user_id, verifier, redirect)
            return google.authorize_url(redirect, state, challenge)
        if connection.kind != "mcp_http":
            raise ConnectionError_(f"{connection.name} does not sign in")
        loop = asyncio.get_running_loop()
        old = self.sign_ins.pop(connection.id, None)
        if old is not None and old.task is not None:
            old.task.cancel()
        worker = self.workers.pop(connection.id, None)
        if worker is not None:
            await worker.close()  # a fresh client, so the sign-in happens now
        pending = SignIn(connection.id, user_id, loop.create_future(), loop.create_future())
        self.sign_ins[connection.id] = pending

        async def finish() -> None:
            try:
                await self.refresh(user_id, connection_id)
            finally:
                if self.sign_ins.get(connection.id) is pending:
                    self.sign_ins.pop(connection.id, None)

        pending.task = asyncio.ensure_future(finish())
        done, _ = await asyncio.wait(
            {pending.url, pending.task}, timeout=30, return_when="FIRST_COMPLETED"
        )
        if pending.url in done:
            return pending.url.result()
        return None

    async def signed_in(self, state: str, code: str | None, error: str | None = None) -> str:
        """The browser came back from the service: hand the code to the waiting sign-in."""
        pending = self.by_state.pop(state, None)
        if isinstance(pending, GoogleSignIn):
            return await self._google_signed_in(pending, code, error)
        from mcp.shared.auth import AuthorizationCodeResult

        if pending is None or pending.code.done():
            raise ConnectionError_("this sign-in has expired: start it again from Your connections")
        if error or not code:
            pending.code.set_exception(NeedsSignIn(f"the service said: {error or 'no code'}"))
            raise ConnectionError_(f"the service did not sign you in ({error or 'no code'})")
        pending.code.set_result(AuthorizationCodeResult(code=code, state=state))
        return self.get(pending.user_id, pending.connection_id).name

    async def _google_signed_in(
        self, pending: GoogleSignIn, code: str | None, error: str | None
    ) -> str:
        connection = self.get(pending.user_id, pending.connection_id)
        google = self.google()
        if error or not code or google is None:
            raise ConnectionError_(f"Google did not sign you in ({error or 'no code'})")
        tokens = await google.exchange(code, pending.redirect_uri, pending.verifier)
        secret = {"tokens": tokens}
        sealed = self.sealer().seal(secret, f"{connection.user_id}:{connection.id}")
        self.store.execute(
            "UPDATE connections SET secret = ?, status = 'ok', error = NULL, checked_at = ? "
            "WHERE id = ?",
            (sealed, self.clock(), connection.id),
        )
        return connection.name

    async def _builtin_call(self, connection: Connection, name: str, args: dict[str, Any]) -> Any:
        secret = self._secret(connection)
        if connection.kind == "telegram":
            client = self.telegrams.get(connection.id)
            if client is None:
                if not secret.get("session"):
                    raise NeedsSignIn("finish signing in to Telegram first")
                client = self.telegram(secret["api_id"], secret["api_hash"], secret["session"])
                self.telegrams[connection.id] = client
            return await client.call(name, args)
        if connection.kind == "imap":
            box = self.mailbox(secret["host"], secret["user"], secret["password"], secret["port"])
            return await box.call(name, args)
        google = self.google()
        if google is None:
            raise ConnectionError_("this server no longer offers Google")
        tokens = secret.get("tokens") or {}
        if not tokens:
            raise NeedsSignIn("sign in to Google first")

        def save(fresh: dict[str, Any]) -> None:
            secret["tokens"] = fresh
            sealed = self.sealer().seal(secret, f"{connection.user_id}:{connection.id}")
            self.store.execute(
                "UPDATE connections SET secret = ? WHERE id = ?", (sealed, connection.id)
            )

        try:
            token = await google.access(tokens, save)
        except ToolError as exc:
            self.store.execute(
                "UPDATE connections SET status = 'needs_auth', error = ? WHERE id = ?",
                (str(exc), connection.id),
            )
            raise
        if name == "mail_search":
            limit = max(1, min(int(args.get("max") or 10), 20))
            return await google.mail_search(token, str(args.get("query") or ""), limit)
        if name == "mail_read":
            return await google.mail_read(token, str(args.get("id") or ""))
        if name == "calendar_events":
            import datetime as dt

            zone = (self.zone_for(connection.user_id) if self.zone_for else None) or dt.UTC
            return await google.calendar_events(
                token, args.get("start"), args.get("end"), args.get("query"), zone
            )
        raise ConnectionError_(f"no tool {name}")

    async def refresh(self, user_id: int, connection_id: str) -> Connection:
        """Fetch the server's tools again, keeping the person's choices for known ones."""
        connection = self.get(user_id, connection_id)
        if connection.kind in ("google", "imap", "telegram"):
            secret = self._secret(connection)
            if connection.kind == "telegram":
                status = "ok" if secret.get("session") else connection.status
                error = None
            elif connection.kind == "google":
                status = "ok" if secret.get("tokens") else "needs_auth"
                error = None if status == "ok" else "sign in with Google"
            else:
                try:
                    box = self.mailbox(
                        secret["host"], secret["user"], secret["password"], secret["port"]
                    )
                    await asyncio.to_thread(box.check)
                    status, error = "ok", None
                except ToolError as exc:
                    status, error = "error", str(exc)
            self.store.execute(
                "UPDATE connections SET status = ?, error = ?, checked_at = ? WHERE id = ?",
                (status, error, self.clock(), connection.id),
            )
            return self.get(user_id, connection_id)
        before = {t["mcp_name"]: t for t in connection.tools}
        try:
            listed = await self._worker(connection).request("list")
        except Exception as exc:
            needs = isinstance(exc, NeedsSignIn) or "sign in" in str(exc)
            message = str(exc)[:300] or type(exc).__name__
            self.store.execute(
                "UPDATE connections SET status = ?, error = ?, checked_at = ? WHERE id = ?",
                ("needs_auth" if needs else "error", message, self.clock(), connection.id),
            )
            return self.get(user_id, connection_id)
        tools = []
        for tool in listed:
            description = " ".join(str(tool.description or tool.title or "").split())[:800]
            minimum = mcp.default_tier(tool.name, description, tool.annotations)
            kept = before.get(tool.name, {})
            tools.append(
                {
                    "name": mcp.tool_name(connection.slug, tool.name),
                    "mcp_name": tool.name,
                    "description": description,
                    "schema": tool.input_schema if isinstance(tool.input_schema, dict) else {},
                    "min_tier": minimum,
                    "tier": max(minimum, int(kept.get("tier", minimum))),
                    "enabled": bool(kept.get("enabled", len(tools) < self.config.max_tools)),
                }
            )
        self.store.execute(
            "UPDATE connections SET tools = ?, status = 'ok', error = NULL, checked_at = ? "
            "WHERE id = ?",
            (json.dumps(tools), self.clock(), connection.id),
        )
        return self.get(user_id, connection_id)

    async def call(
        self, user_id: int, connection_id: str, mcp_name: str, arguments: dict[str, Any]
    ) -> str:
        connection = self.get(user_id, connection_id)
        if not connection.enabled:
            raise ConnectionError_(f"{connection.name} is switched off")
        if connection.kind in ("google", "imap", "telegram"):
            return await self._builtin_call(connection, mcp_name, arguments)
        result = await self._worker(connection).request("call", (mcp_name, arguments))
        return mcp.result_text(result)

    def tools_for(self, user_id: int) -> list[PersonalTool]:
        """This person's connected tools that are switched on, as their own tools."""
        out: list[PersonalTool] = []
        for connection in self.for_user(user_id):
            if not connection.enabled or connection.status != "ok":
                continue
            offered = [t for t in connection.tools if t.get("enabled")][: self.config.max_tools]
            for tool in offered:
                out.append(self._personal(connection, tool))
        return out

    def _personal(self, connection: Connection, tool: dict[str, Any]) -> PersonalTool:
        user_id, connection_id, mcp_name = connection.user_id, connection.id, tool["mcp_name"]

        async def run(arguments: dict[str, Any]) -> Any:
            return await self.call(user_id, connection_id, mcp_name, arguments)

        schema = tool.get("schema") or {}
        if schema.get("type") != "object":
            schema = {"type": "object", "properties": {}}
        return PersonalTool(
            name=tool["name"],
            description=f"{connection.name}: {tool.get('description') or mcp_name}",
            parameters=schema,
            tier=max(int(tool.get("tier", 2)), int(tool.get("min_tier", 2))),
            source="connector",
            label=connection.name,
            run=run,
            skill="connections",
        )

    async def close(self) -> None:
        for client in [*self.telegrams.values(), *(login[0] for login in self.logins.values())]:
            await client.close()
        self.telegrams.clear()
        self.logins.clear()
        for pending in list(self.sign_ins.values()):
            if pending.task is not None:
                pending.task.cancel()
        self.sign_ins.clear()
        for worker in list(self.workers.values()):
            await worker.close()
        self.workers.clear()
