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


class ApprovalsView(BaseModel):
    minutes: int = Field(description="How long a PIN on screen control covers; 0 is off.")
    windows: list[ApprovalWindowView]


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
