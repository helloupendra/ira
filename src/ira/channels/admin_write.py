"""The admin console's writes under ``/v1/admin``.

Every route here needs a signed-in session (never an API token), checks the
role, and writes one row to the change log: who, what, when, and the value
before and after where there is one.

* Users, invitations and other people's sessions need ``users`` (owner only).
* Tokens, tools, model chains and settings need ``admin.write`` (owner, admin).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import ValidationError

from ira import changes, overrides
from ira.accounts import AccountError, LastOwnerError, Principal, parse_scopes
from ira.channels.account import end_session
from ira.channels.admin import invite_view, settings_view, tool_detail
from ira.channels.deps import get_runtime, require_session
from ira.channels.schemas import (
    ERRORS,
    AdminUserRow,
    ErrorDetail,
    InviteCreated,
    InviteCreateRequest,
    ModelTestRequest,
    ModelTestResult,
    OkResponse,
    RoleChange,
    SettingsUpdate,
    SettingsView,
    TierOrderRequest,
    TierView,
    TokenCreated,
    TokenCreateRequest,
    ToolDetail,
    ToolSwitch,
    ToolTestRequest,
    ToolTestResult,
)
from ira.runtime import Runtime
from ira.tools.registry import ToolError, validation_message

router = APIRouter(
    prefix="/v1/admin",
    tags=["admin: changes"],
    responses={
        **ERRORS,
        404: {
            "model": ErrorDetail,
            "description": "No such user, invite, session, token, tool or tier",
        },
        409: {
            "model": ErrorDetail,
            "description": "The last owner cannot go, or an action tool cannot be tested",
        },
    },
)
owner = require_session("users")
writer = require_session("admin.write")

TOOL_TEST_SECONDS = 30
MAX_RESULT_CHARS = 20_000


def _log(runtime: Runtime, who: Principal, what: str, target: str | None, **values: Any) -> None:
    changes.record(runtime.store, who.actor, what, target, **values)


# Users and invitations (owner only).


@router.post("/users/invites", response_model=InviteCreated, summary="Invite someone by link")
def create_invite(
    body: InviteCreateRequest,
    who: Principal = Depends(owner),
    runtime: Runtime = Depends(get_runtime),
) -> InviteCreated:
    try:
        token, invite = runtime.accounts.create_invite(body.email, body.role, who.user.email)
    except AccountError as exc:
        raise HTTPException(400, detail=str(exc)) from None
    _log(runtime, who, "user.invited", invite.email, after=invite.role)
    # The token travels in the fragment, which browsers never send to a server.
    return InviteCreated(
        invite=invite_view(runtime, invite), token=token, path=f"/admin/invite#token={token}"
    )


@router.delete(
    "/users/invites/{invite_id}", response_model=OkResponse, summary="Withdraw an invitation"
)
def revoke_invite(
    invite_id: str, who: Principal = Depends(owner), runtime: Runtime = Depends(get_runtime)
) -> OkResponse:
    invite = runtime.accounts.get_invite(invite_id)
    if invite is None or not runtime.accounts.revoke_invite(invite_id):
        raise HTTPException(404, detail="no open invitation with that id")
    _log(runtime, who, "user.invite_withdrawn", invite.email, before=invite.role)
    return OkResponse()


def _user_or_404(runtime: Runtime, user_id: int) -> Any:
    user = runtime.accounts.get_user(user_id)
    if user is None:
        raise HTTPException(404, detail="no such user")
    return user


@router.patch("/users/{user_id}", response_model=AdminUserRow, summary="Change a user's role")
def change_role(
    user_id: int,
    body: RoleChange,
    who: Principal = Depends(owner),
    runtime: Runtime = Depends(get_runtime),
) -> AdminUserRow:
    _user_or_404(runtime, user_id)
    try:
        user, before = runtime.accounts.set_role(user_id, body.role)
    except LastOwnerError as exc:
        raise HTTPException(409, detail=str(exc)) from None
    except AccountError as exc:
        raise HTTPException(400, detail=str(exc)) from None
    if before != user.role:
        _log(runtime, who, "user.role", user.email, before=before, after=user.role)
    return AdminUserRow(**user.public(), has_pin=user.has_pin)


@router.delete("/users/{user_id}", response_model=OkResponse, summary="Remove a user")
def remove_user(
    user_id: int, who: Principal = Depends(owner), runtime: Runtime = Depends(get_runtime)
) -> OkResponse:
    _user_or_404(runtime, user_id)
    try:
        user = runtime.accounts.remove_user(user_id)
    except LastOwnerError as exc:
        raise HTTPException(409, detail=str(exc)) from None
    _log(runtime, who, "user.removed", user.email, before=user.role)
    return OkResponse()


@router.post(
    "/users/{user_id}/reset-pin",
    response_model=OkResponse,
    summary="Clear a user's action PIN; they set a new one",
)
def reset_pin(
    user_id: int, who: Principal = Depends(owner), runtime: Runtime = Depends(get_runtime)
) -> OkResponse:
    user = _user_or_404(runtime, user_id)
    runtime.guard.clear_pin(user_id, actor=who.actor, channel=who.channel)
    _log(runtime, who, "user.pin_reset", user.email, before=user.has_pin, after=False)
    return OkResponse()


# Sessions (owner only).


@router.delete(
    "/sessions/{session_id}", response_model=OkResponse, summary="Sign out any user's session"
)
def revoke_session(
    session_id: str,
    response: Response,
    who: Principal = Depends(owner),
    runtime: Runtime = Depends(get_runtime),
) -> OkResponse:
    session = runtime.accounts.get_session(session_id)
    if session is None:
        raise HTTPException(404, detail="no active session with that id")
    end_session(runtime, who, response, session)
    return OkResponse()


# API tokens.


@router.post(
    "/tokens", response_model=TokenCreated, summary="Create an API token for yourself (shown once)"
)
def create_token(
    body: TokenCreateRequest,
    who: Principal = Depends(writer),
    runtime: Runtime = Depends(get_runtime),
) -> TokenCreated:
    try:
        scopes = parse_scopes(body.scopes)
        token, token_id = runtime.accounts.create_token(who.user, body.label, scopes)
    except AccountError as exc:
        raise HTTPException(400, detail=str(exc)) from None
    label = body.label.strip() or "token"
    _log(runtime, who, "token.created", token_id, after={"label": label, "scopes": scopes})
    return TokenCreated(id=token_id, label=label, scopes=scopes, token=token)


@router.delete("/tokens/{token_id}", response_model=OkResponse, summary="Revoke an API token")
def revoke_token(
    token_id: str, who: Principal = Depends(writer), runtime: Runtime = Depends(get_runtime)
) -> OkResponse:
    row = runtime.accounts.get_token(token_id)
    if row is None or not runtime.accounts.revoke_token_id(token_id):
        raise HTTPException(404, detail="no active token with that id")
    _log(
        runtime,
        who,
        "token.revoked",
        token_id,
        before={"label": row["label"], "owner": row["email"], "scopes": row["scopes"]},
    )
    return OkResponse()


# Tools.


def _tool_or_404(runtime: Runtime, name: str) -> Any:
    tool = runtime.registry.get(name)
    if tool is None:
        raise HTTPException(404, detail="no such tool")
    return tool


@router.patch("/tools/{name}", response_model=ToolDetail, summary="Switch a tool on or off")
def switch_tool(
    name: str,
    body: ToolSwitch,
    who: Principal = Depends(writer),
    runtime: Runtime = Depends(get_runtime),
) -> ToolDetail:
    _tool_or_404(runtime, name)
    before = runtime.registry.is_enabled(name)
    overrides.set_tool_enabled(runtime, name, body.enabled)
    if before != body.enabled:
        _log(runtime, who, "tool.enabled", name, before=before, after=body.enabled)
    return tool_detail(runtime, name)


def _jsonable(value: Any) -> Any:
    text = json.dumps(value, default=str)
    if len(text) > MAX_RESULT_CHARS:
        return text[:MAX_RESULT_CHARS] + "... (truncated)"
    return json.loads(text)


@router.post(
    "/tools/{name}/test",
    response_model=ToolTestResult,
    summary="Run a read tool with test parameters (never an action)",
)
async def test_tool(
    name: str,
    body: ToolTestRequest,
    who: Principal = Depends(writer),
    runtime: Runtime = Depends(get_runtime),
) -> ToolTestResult:
    tool = _tool_or_404(runtime, name)
    if tool.kind != "read":
        raise HTTPException(
            409, detail="action tools cannot be tested here; they only run after a PIN"
        )
    _log(runtime, who, "tool.tested", name, after=body.params)
    started = time.monotonic()
    try:
        args = tool.validate(body.params)
        positional, keywords = tool.call_args(args)
        if inspect.iscoroutinefunction(tool.fn):
            call = tool.fn(*positional, **keywords)
        else:
            call = asyncio.to_thread(tool.fn, *positional, **keywords)
        value = await asyncio.wait_for(call, timeout=TOOL_TEST_SECONDS)
    except ValidationError as exc:
        error = f"invalid parameters: {validation_message(exc)}"
    except ToolError as exc:
        error = str(exc)
    except TimeoutError:
        error = f"no result in {TOOL_TEST_SECONDS} seconds"
    except Exception as exc:
        error = f"the tool raised {type(exc).__name__}"
    else:
        seconds = round(time.monotonic() - started, 3)
        return ToolTestResult(ok=True, seconds=seconds, result=_jsonable(value))
    return ToolTestResult(ok=False, seconds=round(time.monotonic() - started, 3), error=error)


# Models.


def _configured_refs(runtime: Runtime) -> set[str]:
    return {ref for refs in runtime.gateway.tiers.values() for ref in refs}


@router.post(
    "/models/test",
    response_model=ModelTestResult,
    summary="Ask one model a fixed short question; reports ok and latency",
)
async def test_model(
    body: ModelTestRequest,
    who: Principal = Depends(writer),
    runtime: Runtime = Depends(get_runtime),
) -> ModelTestResult:
    if body.ref not in _configured_refs(runtime):
        raise HTTPException(404, detail="that model is not in any tier in ira.yaml")
    response, error, seconds = await runtime.gateway.probe(body.ref)
    _log(runtime, who, "model.tested", body.ref, after={"ok": error is None})
    if error is not None:
        return ModelTestResult(
            ref=body.ref, ok=False, seconds=seconds, error_kind=error.kind, error=str(error)[:300]
        )
    text = (response.text if response else "").strip()
    return ModelTestResult(ref=body.ref, ok=True, seconds=seconds, text=text[:200])


@router.put(
    "/models/tiers/{tier}",
    response_model=TierView,
    summary="Reorder a tier's fallback chain (null order goes back to ira.yaml)",
)
def order_tier(
    tier: str,
    body: TierOrderRequest,
    who: Principal = Depends(writer),
    runtime: Runtime = Depends(get_runtime),
) -> TierView:
    before = list(runtime.gateway.tiers.get(tier, []))
    try:
        chain = overrides.set_tier_order(runtime, tier, body.order)
    except overrides.OverrideError as exc:
        status = 404 if tier not in runtime.settings.models.tiers else 400
        raise HTTPException(status, detail=str(exc)) from None
    if chain != before:
        _log(runtime, who, "model.chain", tier, before=before, after=chain)
    return TierView(
        name=tier,
        configured=overrides.configured_chain(runtime, tier),
        chain=chain,
        overridden=overrides.tier_override(runtime, tier) is not None,
        used_by_assistant=tier == runtime.assistant.tier,
    )


# Settings.


@router.patch(
    "/settings",
    response_model=SettingsView,
    summary="Rename the assistant or choose its voice (null goes back to ira.yaml)",
)
def update_settings(
    body: SettingsUpdate,
    who: Principal = Depends(writer),
    runtime: Runtime = Depends(get_runtime),
) -> SettingsView:
    try:
        if "name" in body.model_fields_set:
            before = runtime.assistant.name
            after = overrides.set_name(runtime, body.name)
            if after != before:
                _log(runtime, who, "settings.name", None, before=before, after=after)
        if "voice" in body.model_fields_set:
            before_voice = overrides.current_voice(runtime)
            after_voice = overrides.set_voice(runtime, body.voice)
            if after_voice != before_voice:
                _log(runtime, who, "settings.voice", None, before=before_voice, after=after_voice)
    except overrides.OverrideError as exc:
        raise HTTPException(400, detail=str(exc)) from None
    return settings_view(runtime)
