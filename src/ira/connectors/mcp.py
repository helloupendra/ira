"""MCP: tiers from a tool's annotations, its name as Ira's tool, and one worker per connection.

Annotations are hints from the server, so they can only make a tool stricter:
``readOnlyHint`` makes it Tier 0; anything else is Tier 2 (read back, then a
yes); ``destructiveHint``, or a name or description about sending, paying,
sharing, deleting, merging or pushing, makes it Tier 3 (the PIN). A person may
raise a tool's tier, never lower it.

The SDK's client must be opened and closed in the same task, so each live
connection has one worker task that holds the client and takes calls from a
queue, and closes after a few idle minutes.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import logging
import re
import socket
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from ira.tools.registry import ToolError

log = logging.getLogger("ira.connectors")

IDLE_SECONDS = 300.0
CALL_SECONDS = 60.0
MAX_RESULT_CHARS = 24_000
MAX_PAGES = 10

SENSITIVE = re.compile(
    r"\b(send|sends|sending|email|mail_send|pay|payment|transfer|refund|share|sharing|publish|"
    r"post|delete|deletes|remove|drop|destroy|merge|push|force|revoke|invite|transfer)\b",
    re.IGNORECASE,
)


def tool_name(slug: str, name: str) -> str:
    """The MCP tool's name as Ira's: the connection's slug first, a-z, 0-9 and _ only."""
    raw = f"{slug}_{name}".lower()
    clean = re.sub(r"_+", "_", re.sub(r"[^a-z0-9_]", "_", raw)).strip("_")
    if not clean or not clean[0].isalpha():
        clean = "c_" + clean
    return clean[:60]


def default_tier(name: str, description: str, annotations: Any) -> int:
    def hint(key: str) -> Any:
        if annotations is None:
            return None
        if isinstance(annotations, dict):
            return annotations.get(key)
        return getattr(annotations, key, None)

    words = f"{name.replace('_', ' ')} {description}"
    if hint("destructive_hint") is True or hint("destructiveHint") is True:
        return 3
    if SENSITIVE.search(name.replace("_", " ")):
        return 3
    if hint("read_only_hint") is True or hint("readOnlyHint") is True:
        return 0
    if SENSITIVE.search(words):
        return 3
    return 2


def check_url(url: str, allow_private: bool = False) -> str:
    """A remote MCP server's address: https, and not on a private network unless allowed."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ToolError("the address must start with https://")
    if parts.scheme == "http" and not allow_private:
        raise ToolError("use https:// for a server on another machine")
    if not allow_private:
        resolve(parts.hostname, parts.port or 443)
    return url.strip()


def _private(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def resolve(host: str, port: int, allow_private: bool = False) -> str:
    """The address to connect to for [host], checked now: every address the name has must be
    public (unless allowed), and the connection is then made to the one returned. Checking
    only when a connection is added is not enough: a name can later answer with this machine
    or the cloud's metadata service (169.254.169.254)."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError:
        raise ToolError(f"{host} could not be found") from None
    addresses = [str(info[4][0]) for info in infos]
    if not addresses:
        raise ToolError(f"{host} could not be found")
    if not allow_private and any(_private(a) for a in addresses):
        raise ToolError(
            f"{host} is on a private network; the server's operator can allow that with "
            "connectors.allow_private"
        )
    return addresses[0]


def pinned_backend(allow_private: bool) -> Any:
    """httpcore's network backend for a connection's client: each connection, the first and
    any a redirect leads to, goes to an address checked just before, so DNS cannot change it
    in between. TLS still checks the certificate against the name."""
    import httpcore2
    from httpcore2._backends.auto import AutoBackend

    class Pinned(httpcore2.AsyncNetworkBackend):
        def __init__(self) -> None:
            self.inner = AutoBackend()

        async def connect_tcp(
            self, host: str, port: int, timeout: float | None = None,
            local_address: str | None = None, socket_options: Any = None,
        ) -> Any:  # fmt: skip
            try:
                address = await asyncio.to_thread(resolve, host, port, allow_private)
            except ToolError as exc:
                raise httpcore2.ConnectError(str(exc)) from None
            return await self.inner.connect_tcp(
                address, port, timeout, local_address, socket_options
            )

        async def connect_unix_socket(
            self, path: str, timeout: float | None = None, socket_options: Any = None
        ) -> Any:
            raise httpcore2.ConnectError("a connection never uses a local socket")

        async def sleep(self, seconds: float) -> None:
            await self.inner.sleep(seconds)

    return Pinned()


def result_text(result: Any) -> str:
    """A tool result as text for the model: its text, structured data, or what else it holds."""
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        kind = getattr(block, "type", None)
        if kind == "text":
            parts.append(str(getattr(block, "text", "")))
        elif kind == "resource":
            resource = getattr(block, "resource", None)
            parts.append(str(getattr(resource, "text", None) or getattr(resource, "uri", "")))
        elif kind == "resource_link":
            parts.append(f"[{getattr(block, 'name', '')}: {getattr(block, 'uri', '')}]")
        elif kind in ("image", "audio"):
            parts.append(f"[{kind}]")
    structured = getattr(result, "structured_content", None)
    if structured and not parts:
        parts.append(json.dumps(structured, ensure_ascii=False, default=str))
    text = "\n".join(p for p in parts if p).strip() or "(no content)"
    if getattr(result, "is_error", False):
        raise ToolError(text[:500])
    return text[:MAX_RESULT_CHARS]


def pinned_client(headers: dict[str, str], auth: Any = None, allow_private: bool = False) -> Any:
    """The HTTP client for a connection: every connection it makes (sign-in, calls, redirects)
    goes to an address checked just before."""
    import httpcore2
    import httpx2

    transport = httpx2.AsyncHTTPTransport()
    pool = transport._pool
    if not isinstance(pool, httpcore2.AsyncConnectionPool):
        raise ToolError("connections cannot go through a proxy")
    # Never silently unpinned: if a new httpcore names this otherwise, refuse to connect.
    if not hasattr(pool, "_network_backend"):
        raise ToolError("this server's HTTP library cannot check connections' addresses")
    pool._network_backend = pinned_backend(allow_private)
    return httpx2.AsyncClient(
        headers=headers,
        auth=auth,
        timeout=httpx2.Timeout(30.0, read=CALL_SECONDS),
        transport=transport,
    )


def http_transport(
    url: str, headers: dict[str, str], auth: Any = None, allow_private: bool = False
) -> Any:
    from mcp.client.streamable_http import streamable_http_client

    client = pinned_client(headers, auth, allow_private)
    return streamable_http_client(url, http_client=client)


def stdio_target(command: str, args: list[str], env: dict[str, str]) -> Any:
    from mcp import StdioServerParameters
    from mcp.client.stdio import get_default_environment

    return StdioServerParameters(
        command=command, args=args, env={**get_default_environment(), **env}
    )


class Worker:
    """One live MCP client, used from its own task: list tools and call them."""

    def __init__(self, target_factory: Callable[[], Any], label: str) -> None:
        self.target_factory = target_factory
        self.label = label
        self.queue: asyncio.Queue[tuple[str, Any, asyncio.Future[Any]]] = asyncio.Queue()
        self.task: asyncio.Task[None] | None = None
        self.last_used = time.monotonic()

    def alive(self) -> bool:
        return self.task is not None and not self.task.done()

    async def request(self, method: str, payload: Any = None) -> Any:
        if not self.alive():
            self.task = asyncio.ensure_future(self._run())
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self.queue.put_nowait((method, payload, future))
        self.last_used = time.monotonic()
        try:
            return await asyncio.wait_for(future, CALL_SECONDS + 15)
        except TimeoutError:
            raise ToolError(f"{self.label} did not answer in time") from None

    async def close(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
            self.task = None

    async def _run(self) -> None:
        from mcp import Client

        pending: tuple[str, Any, asyncio.Future[Any]] | None = None
        try:
            async with Client(self.target_factory(), read_timeout_seconds=CALL_SECONDS) as client:
                while True:
                    try:
                        pending = await asyncio.wait_for(self.queue.get(), IDLE_SECONDS)
                    except TimeoutError:
                        return  # idle: close the client in this same task
                    method, payload, future = pending
                    try:
                        if method == "list":
                            future.set_result(await _list_tools(client))
                        else:
                            name, arguments = payload
                            future.set_result(await client.call_tool(name, arguments))
                    except Exception as exc:
                        if not future.done():
                            future.set_exception(exc)
                    pending = None
        except Exception as exc:
            log.warning("connection %s failed: %s", self.label, type(exc).__name__)
            failure = ToolError(f"{self.label} could not be reached ({type(exc).__name__})")
            if pending is not None and not pending[2].done():
                pending[2].set_exception(failure)
            while not self.queue.empty():
                _, _, future = self.queue.get_nowait()
                if not future.done():
                    future.set_exception(failure)


async def _list_tools(client: Any) -> list[Any]:
    tools: list[Any] = []
    cursor = None
    for _ in range(MAX_PAGES):
        page = await client.list_tools(cursor=cursor)
        tools.extend(page.tools)
        cursor = page.next_cursor
        if not cursor:
            break
    return tools
