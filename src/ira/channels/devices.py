"""Devices over HTTP: pairing, the device WebSocket, your devices, events, and the admin list.

* ``POST /v1/devices/pair`` (public; the one-time code is the secret): a device
  exchanges its pairing code for its own token.
* ``GET /v1/devices/ws``: the device WebSocket. Only a device token works here,
  and a device token works nowhere else.
* ``/v1/me/devices``: your own devices. Pairing one and switching a skill on
  are new grants, so they need your PIN; switching off never does.
* ``/v1/me/events``: what your devices announced, and a live stream of it.
* ``/v1/admin/devices``: every device, for an owner or admin. They can revoke a
  device and switch its skills off, never on, and never see what it returned.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket
from fastapi.responses import StreamingResponse

from ira import changes
from ira.accounts import Principal
from ira.channels.deps import client_ip, get_runtime, require, require_session
from ira.channels.schemas import (
    ERRORS,
    DevicePaired,
    DeviceToolView,
    DeviceUpdate,
    DeviceView,
    EventView,
    OkResponse,
    PairingCreate,
    PairingState,
    PairingView,
    PairRequest,
    SkillState,
    SkillView,
)
from ira.devices.hub import DeviceHub
from ira.devices.protocol import CLOSE_UNAUTHORIZED
from ira.devices.store import (
    SKILLS,
    Device,
    DeviceError,
    Devices,
    Pairing,
    check_kind,
    check_skills,
    normalise_code,
    show_code,
)
from ira.runtime import Runtime

router = APIRouter(tags=["devices"], responses=ERRORS)

# A device that cannot set a header sends its token as ?token=. Servers log request
# lines, uvicorn included, so the value is masked in every log record that carries one.
_TOKEN_IN_URL = re.compile(r"([?&]token=)[^&\s\"']+")


class TokenFilter(logging.Filter):
    """Mask ``token=...`` in log records: uvicorn logs each WebSocket's path and query."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and record.args:
            record.args = tuple(
                _TOKEN_IN_URL.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args
            )
        if isinstance(record.msg, str) and "token=" in record.msg:
            record.msg = _TOKEN_IN_URL.sub(r"\1***", record.msg)
        return True


def mask_tokens_in_logs() -> None:
    """Install the filter on the loggers that write request lines (once)."""
    for name in ("uvicorn.error", "uvicorn.access", "uvicorn"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, TokenFilter) for f in logger.filters):
            logger.addFilter(TokenFilter())


WEBSOCKET_PATH = "/v1/devices/ws"
KIND_SKILLS: dict[str, tuple[str, ...]] = {"mac": ("chrome", "tasks"), "android": ()}
STREAM_KEEPALIVE = 20.0
PIN_STATUS = {"wrong_pin": 403, "locked": 423, "no_pin": 409}


def hub_of(runtime: Runtime) -> DeviceHub:
    assert runtime.hub is not None
    return runtime.hub


def devices_of(runtime: Runtime) -> Devices:
    return hub_of(runtime).devices


def device_view(runtime: Runtime, device: Device) -> DeviceView:
    on = set(device.skills)
    offered = {tool.get("skill") for tool in device.tools}
    names = [*KIND_SKILLS.get(device.kind, ())]
    names += sorted((offered | on) - set(names) - {None})
    return DeviceView(
        id=device.id,
        kind=device.kind,  # type: ignore[arg-type]
        label=device.label,
        user_id=device.user_id,
        email=device.email,
        created_at=device.created_at,
        last_seen_at=device.last_seen_at,
        connected=hub_of(runtime).connected(device.id),
        version=device.version,
        tools=[
            DeviceToolView(
                name=str(tool.get("name")),
                description=str(tool.get("description", "")),
                skill=str(tool.get("skill", "")),
                tier=int(tool.get("tier", 2)),
                on=tool.get("skill") in on,
            )
            for tool in device.tools
        ],
        skills=[
            SkillState(
                name=name,
                description=SKILLS.get(name, name),
                on=name in on,
                offered=name in offered,
            )
            for name in names
        ],
    )


def _log(runtime: Runtime, who: Principal, what: str, target: str | None, **values: Any) -> None:
    changes.record(runtime.store, who.actor, what, target, channel=who.channel, **values)


async def _check_pin(runtime: Runtime, who: Principal, pin: str | None, what: str) -> None:
    """A new grant is Tier 3: the person's own PIN, with the same lock as actions."""
    if not pin:
        raise HTTPException(403, detail="switching this on needs your PIN")
    outcome = await runtime.guard.check_pin(
        pin, user_id=who.user.id, what=what, actor=who.actor, channel=who.channel
    )
    if outcome.status != "confirmed":
        raise HTTPException(PIN_STATUS.get(outcome.status, 403), detail=outcome.message)


# --- pairing -----------------------------------------------------------------------


def _pairing_view(runtime: Runtime, code: str, pairing: Pairing) -> PairingView:
    import segno

    server = runtime.base_url()
    url = f"{server}/pair#code={code}"
    qr = segno.make(url, error="m").svg_data_uri(scale=6, border=2)
    return PairingView(
        id=pairing.id,
        code=show_code(code),
        expires_at=pairing.expires_at,
        kind=pairing.kind,  # type: ignore[arg-type]
        label=pairing.label,
        skills=pairing.skills,
        server=server,
        pair_url=url,
        qr_svg=qr,
    )


async def start_pairing(runtime: Runtime, who: Principal, body: PairingCreate) -> PairingView:
    devices = devices_of(runtime)
    what = f"pair a {body.kind} with {', '.join(body.skills) or 'no skills'}"
    try:
        # Check the request before the PIN, so a typo costs no attempt.
        check_kind(body.kind)
        check_skills(body.skills)
    except DeviceError as exc:
        raise HTTPException(400, detail=str(exc)) from None
    await _check_pin(runtime, who, body.pin, what)
    code, pairing = devices.start_pairing(who.user.id, body.kind, body.label, body.skills)
    # Never the code: it is a one-time secret.
    _log(
        runtime,
        who,
        "device.pairing_started",
        who.user.email,
        after={"kind": pairing.kind, "label": pairing.label, "skills": pairing.skills},
    )
    return _pairing_view(runtime, code, pairing)


@router.post(
    "/v1/devices/pair",
    response_model=DevicePaired,
    summary="Public: a device exchanges its one-time pairing code for its own token",
    responses={
        410: {"description": "Unknown, used or expired code"},
        429: {"description": "Too many wrong codes from this address; wait 15 minutes"},
    },
)
def pair_device(
    body: PairRequest, request: Request, runtime: Runtime = Depends(get_runtime)
) -> DevicePaired:
    limiter = runtime.accounts.limiter
    key = f"pair:{client_ip(request)}"
    if limiter.blocked(key):
        raise HTTPException(429, detail="too many wrong pairing codes; try again in 15 minutes")
    redeemed = devices_of(runtime).redeem(normalise_code(body.code), body.kind)
    if redeemed is None:
        limiter.fail(key)
        raise HTTPException(
            410,
            detail="this pairing code is not valid any more; make a new one on the Devices page",
        )
    token, device = redeemed
    changes.record(
        runtime.store,
        device.email or str(device.user_id),
        "device.paired",
        str(device.id),
        channel="device",
        after={"kind": device.kind, "label": device.label, "skills": device.skills},
    )
    return DevicePaired(
        device_id=device.id,
        token=token,
        kind=device.kind,  # type: ignore[arg-type]
        label=device.label,
        skills=device.skills,
        name=runtime.assistant.name_for(device.user_id),
        websocket=WEBSOCKET_PATH,
    )


@router.websocket(WEBSOCKET_PATH)
async def device_socket(websocket: WebSocket) -> None:
    """The device WebSocket: ``Authorization: Bearer irad_...`` or ``?token=`` (never logged)."""
    runtime: Runtime = websocket.app.state.runtime
    header = websocket.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    token = token or websocket.query_params.get("token", "")
    device = devices_of(runtime).by_token(token) if token else None
    if device is None:
        # Before accepting: the handshake is refused (HTTP 403).
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return
    await websocket.accept()
    await hub_of(runtime).run(websocket, device)


# --- your devices -------------------------------------------------------------------

asker = require("ask")
your_session = require_session("ask")


def _own_device(runtime: Runtime, who: Principal, device_id: int) -> Device:
    device = devices_of(runtime).get(device_id)
    # Someone else's device is "not found", so the answer does not say it exists.
    if device is None or device.user_id != who.user.id:
        raise HTTPException(404, detail="no such device")
    return device


@router.get("/v1/me/devices", response_model=list[DeviceView], summary="Your paired devices")
def my_devices(
    who: Principal = Depends(asker), runtime: Runtime = Depends(get_runtime)
) -> list[DeviceView]:
    return [device_view(runtime, d) for d in devices_of(runtime).for_user(who.user.id)]


@router.get("/v1/me/skills", response_model=list[SkillView], summary="Skills a device can offer")
def skills(_: Principal = Depends(asker)) -> list[SkillView]:
    return [
        SkillView(
            name=name,
            description=text,
            kinds=[kind for kind, names in KIND_SKILLS.items() if name in names],
        )
        for name, text in SKILLS.items()
    ]


@router.post(
    "/v1/me/devices/pairing",
    response_model=PairingView,
    summary="Pair a new device: a one-time code and QR code (needs your PIN)",
)
async def create_my_pairing(
    body: PairingCreate,
    who: Principal = Depends(your_session),
    runtime: Runtime = Depends(get_runtime),
) -> PairingView:
    return await start_pairing(runtime, who, body)


@router.get(
    "/v1/me/devices/pairings/{pairing_id}",
    response_model=PairingState,
    summary="Whether a device has used your pairing code yet",
)
def my_pairing(
    pairing_id: str, who: Principal = Depends(asker), runtime: Runtime = Depends(get_runtime)
) -> PairingState:
    pairing = devices_of(runtime).pairing(pairing_id)
    if pairing is None or pairing.user_id != who.user.id:
        raise HTTPException(404, detail="no such pairing")
    return PairingState(
        id=pairing.id,
        state=pairing.state(time.time()),  # type: ignore[arg-type]
        device_id=pairing.device_id,
        expires_at=pairing.expires_at,
    )


async def update_device(
    runtime: Runtime, who: Principal, device: Device, body: DeviceUpdate, *, own: bool
) -> DeviceView:
    devices = devices_of(runtime)
    sent = body.model_fields_set
    if "skills" in sent and body.skills is not None:
        try:
            wanted = check_skills(body.skills)
        except DeviceError as exc:
            raise HTTPException(400, detail=str(exc)) from None
        added = [s for s in wanted if s not in device.skills]
        if added and not own:
            raise HTTPException(403, detail="only the device's owner can switch a skill on")
        if added:
            await _check_pin(
                runtime, who, body.pin, f"switch on {', '.join(added)} on {device.label}"
            )
        if wanted != device.skills:
            devices.set_skills(device.id, wanted)
            _log(
                runtime,
                who,
                "device.skills",
                str(device.id),
                before=device.skills,
                after=wanted,
            )
    if "label" in sent and body.label is not None and own:
        label = devices.set_label(device.id, body.label, device.kind)
        if label != device.label:
            _log(runtime, who, "device.renamed", str(device.id), before=device.label, after=label)
    updated = devices.get(device.id)
    assert updated is not None
    return device_view(runtime, updated)


@router.patch(
    "/v1/me/devices/{device_id}",
    response_model=DeviceView,
    summary="Rename a device, or switch its skills (on needs your PIN, off never does)",
)
async def update_my_device(
    device_id: int,
    body: DeviceUpdate,
    who: Principal = Depends(your_session),
    runtime: Runtime = Depends(get_runtime),
) -> DeviceView:
    device = _own_device(runtime, who, device_id)
    return await update_device(runtime, who, device, body, own=True)


async def revoke_device(runtime: Runtime, who: Principal, device: Device) -> None:
    if not devices_of(runtime).revoke(device.id):
        raise HTTPException(404, detail="no such device")
    await hub_of(runtime).disconnect(device.id)
    _log(
        runtime,
        who,
        "device.revoked",
        str(device.id),
        before={"label": device.label, "kind": device.kind, "user": device.email},
    )


@router.delete(
    "/v1/me/devices/{device_id}",
    response_model=OkResponse,
    summary="Revoke one of your devices: its token stops working and it disconnects now",
)
async def revoke_my_device(
    device_id: int, who: Principal = Depends(your_session), runtime: Runtime = Depends(get_runtime)
) -> OkResponse:
    await revoke_device(runtime, who, _own_device(runtime, who, device_id))
    return OkResponse()


# --- your events -------------------------------------------------------------------


@router.get(
    "/v1/me/events",
    response_model=list[EventView],
    summary="What your devices announced in the last seven days, newest first",
)
def my_events(
    limit: int = Query(50, ge=1, le=200),
    who: Principal = Depends(asker),
    runtime: Runtime = Depends(get_runtime),
) -> list[EventView]:
    return [EventView(**row) for row in devices_of(runtime).events(who.user.id, limit)]


@router.delete("/v1/me/events", response_model=OkResponse, summary="Forget your devices' events")
def clear_my_events(
    who: Principal = Depends(your_session), runtime: Runtime = Depends(get_runtime)
) -> OkResponse:
    devices_of(runtime).clear_events(who.user.id)
    return OkResponse()


@router.get(
    "/v1/me/events/stream",
    summary="Your devices' events as server-sent events, as they happen",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {"schema": {"type": "object"}}}}},
)
async def my_event_stream(
    request: Request, who: Principal = Depends(asker), runtime: Runtime = Depends(get_runtime)
) -> StreamingResponse:
    hub = hub_of(runtime)
    queue = hub.subscribe(who.user.id)

    async def stream() -> AsyncIterator[str]:
        try:
            yield ": connected\n\n"
            while True:
                try:
                    row = await asyncio.wait_for(queue.get(), STREAM_KEEPALIVE)
                except TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield ": keepalive\n\n"
                    continue
                data = EventView(**row).model_dump(mode="json")
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        finally:
            hub.unsubscribe(who.user.id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- every device (owner and admin) -------------------------------------------------

manager = require_session("admin.write")


@router.get(
    "/v1/admin/devices",
    response_model=list[DeviceView],
    tags=["admin"],
    summary="Every paired device and its skills (never what a device returned)",
)
def all_devices(
    _: Principal = Depends(manager), runtime: Runtime = Depends(get_runtime)
) -> list[DeviceView]:
    return [device_view(runtime, d) for d in devices_of(runtime).everyone()]


@router.post(
    "/v1/admin/devices",
    response_model=PairingView,
    tags=["admin: changes"],
    summary="Pair a device for yourself: a one-time code (needs your PIN)",
)
async def create_device(
    body: PairingCreate, who: Principal = Depends(manager), runtime: Runtime = Depends(get_runtime)
) -> PairingView:
    return await start_pairing(runtime, who, body)


def _any_device(runtime: Runtime, device_id: int) -> Device:
    device = devices_of(runtime).get(device_id)
    if device is None:
        raise HTTPException(404, detail="no such device")
    return device


@router.patch(
    "/v1/admin/devices/{device_id}",
    response_model=DeviceView,
    tags=["admin: changes"],
    summary="Switch a device's skills off (only its owner switches them on)",
)
async def update_any_device(
    device_id: int,
    body: DeviceUpdate,
    who: Principal = Depends(manager),
    runtime: Runtime = Depends(get_runtime),
) -> DeviceView:
    device = _any_device(runtime, device_id)
    own = device.user_id == who.user.id
    return await update_device(runtime, who, device, body, own=own)


@router.delete(
    "/v1/admin/devices/{device_id}",
    response_model=OkResponse,
    tags=["admin: changes"],
    summary="Revoke any device: its token stops working and it disconnects now",
)
async def revoke_any_device(
    device_id: int, who: Principal = Depends(manager), runtime: Runtime = Depends(get_runtime)
) -> OkResponse:
    await revoke_device(runtime, who, _any_device(runtime, device_id))
    return OkResponse()
