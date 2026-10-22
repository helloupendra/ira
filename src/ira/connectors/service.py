"""Each person's connections: kept, refreshed, offered as their tools, and called."""

from __future__ import annotations

import json
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ira.config import ConnectorsConfig
from ira.connectors import mcp
from ira.connectors.sealed import Sealer
from ira.store import Store
from ira.tools.personal import PersonalTool
from ira.tools.registry import ToolError

SLUG = re.compile(r"[^a-z0-9]+")


class ConnectionError_(ToolError):
    pass


@dataclass
class Connection:
    id: str
    user_id: int
    name: str
    slug: str
    kind: str  # "mcp_http" or "mcp_stdio"
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
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self._sealer = sealer
        self.config = config
        self._target_factory = target_factory
        self.clock = clock
        self.workers: dict[str, mcp.Worker] = {}

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
        self, user_id: int, name: str, url: str, headers: dict[str, str] | None = None
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
        return self._insert(
            user_id, name, "mcp_http", url=url, server=None, secret={"headers": clean}
        )

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

    async def remove(self, user_id: int, connection_id: str) -> None:
        connection = self.get(user_id, connection_id)
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
            return mcp.http_transport(str(connection.url), secret.get("headers") or {})
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

    async def refresh(self, user_id: int, connection_id: str) -> Connection:
        """Fetch the server's tools again, keeping the person's choices for known ones."""
        connection = self.get(user_id, connection_id)
        before = {t["mcp_name"]: t for t in connection.tools}
        try:
            listed = await self._worker(connection).request("list")
        except Exception as exc:
            message = str(exc)[:300] or type(exc).__name__
            self.store.execute(
                "UPDATE connections SET status = 'error', error = ?, checked_at = ? WHERE id = ?",
                (message, self.clock(), connection.id),
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
        for worker in list(self.workers.values()):
            await worker.close()
        self.workers.clear()
