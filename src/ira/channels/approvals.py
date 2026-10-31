"""Your approvals: the windows a PIN on screen control opened, and how long they last."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ira.accounts import Principal
from ira.approvals import valid_minutes
from ira.channels.deps import get_runtime, require, require_session
from ira.channels.devices import _check_pin
from ira.channels.schemas import OkResponse
from ira.runtime import Runtime

router = APIRouter(prefix="/v1/me/approvals", tags=["actions"])


class ApprovalWindowView(BaseModel):
    id: str
    device_id: int
    device: str
    opened_at: float
    expires_at: float
    steps: int = Field(description="Actions it has run so far.")


class TrustedAppsView(BaseModel):
    device_id: int
    device: str
    apps: list[str] = Field(description="Android packages or macOS bundle ids.")


class ApprovalsView(BaseModel):
    minutes: int = Field(description="How long a PIN on screen control covers; 0 is off.")
    windows: list[ApprovalWindowView]
    trusted_apps: list[TrustedAppsView] = Field(default_factory=list)


class TrustedAppsIn(BaseModel):
    device_id: int
    apps: list[str] = Field(max_length=20, description="The whole list for that device.")
    pin: str | None = Field(default=None, max_length=20, description="Needed to add an app.")


class ApprovalMinutes(BaseModel):
    minutes: int = Field(description="0 (off), or 5 to 60.")
    pin: str | None = Field(default=None, max_length=20, description="Needed to raise it.")


def _view(runtime: Runtime, user_id: int) -> ApprovalsView:
    return ApprovalsView(
        minutes=runtime.approval_minutes(user_id),
        windows=[
            ApprovalWindowView(
                id=w.id,
                device_id=w.device_id,
                device=runtime.device_label(w.device_id),
                opened_at=w.opened_at,
                expires_at=w.expires_at,
                steps=w.steps,
            )
            for w in runtime.approvals.for_user(user_id)
        ],
        trusted_apps=[
            TrustedAppsView(device_id=d, device=runtime.device_label(d), apps=apps)
            for d, apps in runtime.approvals.trusted_by_device(user_id).items()
        ],
    )


@router.get("", response_model=ApprovalsView, summary="Your open approval windows")
def my_approvals(
    who: Principal = Depends(require("ask")), runtime: Runtime = Depends(get_runtime)
) -> ApprovalsView:
    return _view(runtime, who.user.id)


@router.delete("", response_model=OkResponse, summary="Stop every approval window of yours")
def stop_all(
    who: Principal = Depends(require("ask")), runtime: Runtime = Depends(get_runtime)
) -> OkResponse:
    runtime.approvals.stop(who.user.id)
    return OkResponse()


@router.delete("/{window_id}", response_model=OkResponse, summary="Stop one approval window")
def stop_one(
    window_id: str,
    who: Principal = Depends(require("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> OkResponse:
    if not runtime.approvals.stop(who.user.id, window_id):
        raise HTTPException(404, detail="no such open approval")
    return OkResponse()


@router.put("/apps", response_model=ApprovalsView, summary="Apps Ira may tap and type in")
async def set_trusted_apps(
    body: TrustedAppsIn,
    who: Principal = Depends(require_session("actions")),
    runtime: Runtime = Depends(get_runtime),
) -> ApprovalsView:
    device = runtime.hub.devices.get(body.device_id) if runtime.hub is not None else None
    if device is None or device.user_id != who.user.id:
        raise HTTPException(404, detail="no such device of yours")
    added = {a.strip() for a in body.apps} - runtime.approvals.trusted(who.user.id, device.id)
    if added:  # more trust: the PIN
        await _check_pin(runtime, who, body.pin, f"let Ira tap and type in {', '.join(added)}")
    runtime.approvals.set_trusted(who.user.id, device.id, body.apps)
    return _view(runtime, who.user.id)


@router.put("/minutes", response_model=ApprovalsView, summary="How long an approval lasts")
async def set_minutes(
    body: ApprovalMinutes,
    who: Principal = Depends(require_session("actions")),
    runtime: Runtime = Depends(get_runtime),
) -> ApprovalsView:
    if not valid_minutes(body.minutes):
        raise HTTPException(422, detail="0 (off), or 5 to 60 minutes")
    if body.minutes > runtime.approval_minutes(who.user.id):  # more trust: the PIN
        await _check_pin(runtime, who, body.pin, f"let approvals last {body.minutes} minutes")
    runtime.assistant.user_settings.set(who.user.id, "approval_minutes", body.minutes)
    if body.minutes == 0:
        runtime.approvals.stop(who.user.id)
    return _view(runtime, who.user.id)


# --- approval keys: a fingerprint on the device instead of the PIN ------------------

keys = APIRouter(prefix="/v1/me/approval-keys", tags=["actions"])


class ApprovalKeyIn(BaseModel):
    public_key: str = Field(
        max_length=1000,
        description="SubjectPublicKeyInfo, DER, base64: EC P-256 for ES256, RSA for RS256.",
    )
    algorithm: str = Field(
        default="ES256", description="ES256, or RS256 (Windows Hello, 2048 bits or more)."
    )
    pin: str = Field(max_length=20, description="The person's PIN, typed on the device.")


class ApprovalKeyView(BaseModel):
    device_id: int
    device: str
    algorithm: str
    created_at: float


@keys.post("", response_model=ApprovalKeyView, summary="Enrol this device's approval key")
async def enrol_key(
    body: ApprovalKeyIn,
    who: Principal = Depends(require("actions")),
    runtime: Runtime = Depends(get_runtime),
) -> ApprovalKeyView:
    """Only a device, with its own token, enrols its key; and only with the person's PIN."""
    from ira.approval_keys import KeyError_

    if who.via != "device" or not (who.credential_id or "").startswith("device:"):
        raise HTTPException(403, detail="a device enrols its own key, with its device token")
    device_id = int((who.credential_id or "device:0").split(":", 1)[1])
    await _check_pin(runtime, who, body.pin, "let this device approve with a fingerprint")
    try:
        key = runtime.approval_keys.enrol(who.user.id, device_id, body.public_key, body.algorithm)
    except KeyError_ as exc:
        raise HTTPException(422, detail=str(exc)) from None
    return ApprovalKeyView(
        device_id=device_id,
        device=runtime.device_label(device_id),
        algorithm=key.algorithm,
        created_at=key.created_at,
    )


@keys.get("", response_model=list[ApprovalKeyView], summary="Devices that may approve")
def my_keys(
    who: Principal = Depends(require("ask")), runtime: Runtime = Depends(get_runtime)
) -> list[ApprovalKeyView]:
    return [
        ApprovalKeyView(
            device_id=k.device_id,
            device=runtime.device_label(k.device_id),
            algorithm=k.algorithm,
            created_at=k.created_at,
        )
        for k in runtime.approval_keys.for_user(who.user.id)
    ]


@keys.delete("/{device_id}", response_model=OkResponse, summary="Remove a device's approval key")
def remove_key(
    device_id: int,
    who: Principal = Depends(require("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> OkResponse:
    if not runtime.approval_keys.remove(who.user.id, device_id):
        raise HTTPException(404, detail="no approval key for that device")
    return OkResponse()
