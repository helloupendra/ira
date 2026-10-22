"""``/v1/me/connections``: each person's own connections to other services (MCP servers).

Connecting needs the person's PIN: it lets Ira use that service for them. A
remote server is a URL and the headers it needs (a token), sealed at rest;
a local server is one the operator offers in ``ira.yaml``, with the secrets
it asks each person for. Every tool gets its tier from its annotations, and
a person may raise a tier, never lower it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ira import changes
from ira.accounts import Principal
from ira.channels.deps import get_runtime, require_session
from ira.channels.learning import check_pin
from ira.channels.schemas import (
    ConnectionCreate,
    ConnectionsView,
    ConnectionUpdate,
    ConnectionView,
    OkResponse,
    ServerOffer,
)
from ira.connectors.sealed import SealError
from ira.runtime import Runtime
from ira.tools.registry import ToolError

router = APIRouter(prefix="/v1/me/connections", tags=["your connections"])
your_session = require_session("ask")


def _available() -> bool:
    try:
        import cryptography  # noqa: F401
        import mcp  # noqa: F401
    except ImportError:
        return False
    return True


def _service(runtime: Runtime):
    if runtime.connectors is None or not _available():
        raise HTTPException(
            501,
            detail='connections need the connectors extra: pip install "ira-assistant[connectors]"',
        )
    return runtime.connectors


def _view(connection) -> ConnectionView:
    return ConnectionView(**connection.public())


def _fail(exc: Exception) -> HTTPException:
    message = str(exc)
    status = 404 if message == "no such connection" else 400
    return HTTPException(status, detail=message)


@router.get("", response_model=ConnectionsView, summary="Your connections, and what you can add")
def my_connections(
    who: Principal = Depends(your_session), runtime: Runtime = Depends(get_runtime)
) -> ConnectionsView:
    available = runtime.connectors is not None and _available()
    connections = runtime.connectors.for_user(who.user.id) if available else []
    servers = runtime.connectors.servers() if available else []
    return ConnectionsView(
        available=available,
        connections=[_view(c) for c in connections],
        servers=[ServerOffer(**s) for s in servers],
    )


@router.post("", response_model=ConnectionView, summary="Connect a service (needs your PIN)")
async def add_connection(
    body: ConnectionCreate,
    who: Principal = Depends(your_session),
    runtime: Runtime = Depends(get_runtime),
) -> ConnectionView:
    service = _service(runtime)
    if bool(body.url) == bool(body.server):
        raise HTTPException(400, detail="give either a url or one of this server's local servers")
    await check_pin(runtime, who, body.pin, f"connecting {body.name}")
    try:
        if body.url:
            connection = service.add_remote(who.user.id, body.name, body.url, body.headers)
        else:
            connection = service.add_server(who.user.id, body.name, str(body.server), body.env)
    except (ToolError, SealError) as exc:
        raise _fail(exc) from None
    changes.record(
        runtime.store,
        who.actor,
        "connection.added",
        connection.name,
        channel=who.channel,
        after={"url": connection.url, "server": connection.server},
    )
    return _view(await service.refresh(who.user.id, connection.id))


@router.post(
    "/{connection_id}/refresh", response_model=ConnectionView, summary="Fetch its tools again"
)
async def refresh_connection(
    connection_id: str,
    who: Principal = Depends(your_session),
    runtime: Runtime = Depends(get_runtime),
) -> ConnectionView:
    service = _service(runtime)
    try:
        return _view(await service.refresh(who.user.id, connection_id))
    except (ToolError, SealError) as exc:
        raise _fail(exc) from None


@router.patch(
    "/{connection_id}",
    response_model=ConnectionView,
    summary="Switch it or its tools on or off, or raise a tool's tier",
)
async def update_connection(
    connection_id: str,
    body: ConnectionUpdate,
    who: Principal = Depends(your_session),
    runtime: Runtime = Depends(get_runtime),
) -> ConnectionView:
    service = _service(runtime)
    try:
        connection = service.get(who.user.id, connection_id)
        if body.enabled and not connection.enabled:
            await check_pin(runtime, who, body.pin, f"switching {connection.name} back on")
        if body.enabled is not None:
            connection = service.set_enabled(who.user.id, connection_id, body.enabled)
        if body.tools:
            changes_asked = {k: v.model_dump(exclude_none=True) for k, v in body.tools.items()}
            connection = service.set_tools(who.user.id, connection_id, changes_asked)
    except (ToolError, SealError) as exc:
        raise _fail(exc) from None
    return _view(connection)


@router.delete("/{connection_id}", response_model=OkResponse, summary="Remove a connection")
async def remove_connection(
    connection_id: str,
    who: Principal = Depends(your_session),
    runtime: Runtime = Depends(get_runtime),
) -> OkResponse:
    service = _service(runtime)
    try:
        connection = service.get(who.user.id, connection_id)
        await service.remove(who.user.id, connection_id)
    except ToolError as exc:
        raise _fail(exc) from None
    changes.record(
        runtime.store, who.actor, "connection.removed", connection.name, channel=who.channel
    )
    return OkResponse()
