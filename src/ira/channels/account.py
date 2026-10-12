"""First-run setup, accepting an invitation, and the signed-in user's own PIN.

Setup and invitations are public routes: each carries its own one-time secret
(the setup code printed by ``ira serve``, or the invitation token), and each
signs the new user in with the session cookie.
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ira import __version__, changes
from ira.accounts import AccountError, Principal
from ira.channels.deps import (
    SESSION_COOKIE,
    client_ip,
    get_principal,
    get_runtime,
    require_session,
    start_browser_session,
)
from ira.channels.schemas import (
    ErrorDetail,
    InviteAcceptRequest,
    InviteTokenRequest,
    OkResponse,
    PinSetRequest,
    PinStatus,
    PublicInvite,
    SessionResponse,
    SessionsEnded,
    SessionView,
    SetupOwnerRequest,
    SetupStatus,
)
from ira.runtime import Runtime

router = APIRouter(prefix="/v1", tags=["setup and account"])
signed_in = require_session()


def _errors(**codes: str) -> dict[int | str, dict[str, Any]]:
    return {
        int(code[1:]): {"model": ErrorDetail, "description": text} for code, text in codes.items()
    }


def claim_setup(
    runtime: Runtime,
    request: Request,
    response: Response,
    code: str,
    email: str,
    password: str,
) -> SessionResponse:
    """Create the first owner with the one-time setup code, then retire the code."""
    expected = runtime.ensure_setup_code()
    if expected is None:
        raise HTTPException(409, detail="setup is already done; sign in instead")
    limiter = runtime.accounts.limiter
    key = f"setup:{client_ip(request)}"
    if limiter.blocked(key):
        raise HTTPException(429, detail="too many wrong setup codes; try again in 15 minutes")
    if not secrets.compare_digest(code.strip().upper().encode(), expected.encode()):
        limiter.fail(key)
        raise HTTPException(403, detail="wrong setup code; `ira serve` printed it at start-up")
    try:
        user = runtime.accounts.create_first_owner(email, password)
    except AccountError as exc:
        # Lost a race to another setup: the other request created the owner.
        status = 409 if not runtime.accounts.needs_owner() else 400
        raise HTTPException(status, detail=str(exc)) from None
    runtime.setup_code = None
    changes.record(runtime.store, f"{user.email} via setup", "setup.owner", user.email)
    return start_browser_session(runtime, request, response, user.id)


@router.get(
    "/setup/status", response_model=SetupStatus, summary="Public: does this install need an owner?"
)
def setup_status(runtime: Runtime = Depends(get_runtime)) -> SetupStatus:
    return SetupStatus(
        needs_owner=runtime.accounts.needs_owner(),
        name=runtime.assistant.name,
        version=__version__,
    )


@router.post(
    "/setup/owner",
    response_model=SessionResponse,
    summary="Create the first owner with the setup code (works once)",
    responses=_errors(
        e400="Bad email or a password under 10 characters",
        e403="Wrong setup code",
        e409="Setup is already done",
        e429="Too many wrong codes from this address; wait 15 minutes",
    ),
)
def setup_owner(
    body: SetupOwnerRequest,
    request: Request,
    response: Response,
    runtime: Runtime = Depends(get_runtime),
) -> SessionResponse:
    return claim_setup(runtime, request, response, body.code, body.email, body.password)


# Invitations.


@router.post(
    "/invites/lookup",
    response_model=PublicInvite,
    summary="Public: who an invitation is for, if it is still open",
    responses=_errors(e410="Unknown, used, withdrawn or expired"),
)
def invite_lookup(
    body: InviteTokenRequest, runtime: Runtime = Depends(get_runtime)
) -> PublicInvite:
    invite = runtime.accounts.open_invite(body.token)
    if invite is None:
        raise HTTPException(410, detail="this invitation is not valid any more; ask for a new one")
    return PublicInvite(email=invite.email, role=invite.role, expires_at=invite.expires_at)


@router.post(
    "/invites/accept",
    response_model=SessionResponse,
    summary="Public: set a password for an invitation and sign in",
    responses=_errors(
        e400="A password under 10 characters, or the email already has an account",
        e410="Unknown, used, withdrawn or expired",
    ),
)
def invite_accept(
    body: InviteAcceptRequest,
    request: Request,
    response: Response,
    runtime: Runtime = Depends(get_runtime),
) -> SessionResponse:
    try:
        user = runtime.accounts.accept_invite(body.token, body.password)
    except AccountError as exc:
        gone = "not valid any more" in str(exc)
        raise HTTPException(410 if gone else 400, detail=str(exc)) from None
    changes.record(
        runtime.store, f"{user.email} via invite", "user.joined", user.email, after=user.role
    )
    return start_browser_session(runtime, request, response, user.id)


# The signed-in user's own action PIN.


def _pin_status(runtime: Runtime, principal: Principal) -> PinStatus:
    locked = runtime.guard.locked_until()
    return PinStatus(
        has_pin=runtime.guard.has_pin(principal.user.id),
        can_confirm="actions" in principal.user.permissions,
        locked_seconds=None if locked is None else max(0, round(locked - runtime.guard.clock())),
    )


@router.get(
    "/me/pin",
    response_model=PinStatus,
    summary="Whether you have an action PIN",
    responses=_errors(e401="Not signed in"),
)
def my_pin(
    principal: Principal = Depends(get_principal), runtime: Runtime = Depends(get_runtime)
) -> PinStatus:
    return _pin_status(runtime, principal)


@router.put(
    "/me/pin",
    response_model=OkResponse,
    summary="Set or change your action PIN (needs your password again)",
    responses=_errors(
        e401="Not signed in",
        e403="Wrong password, an API token, a role without actions, or no CSRF header",
        e429="Too many wrong passwords; wait 15 minutes",
    ),
)
def set_my_pin(
    body: PinSetRequest,
    request: Request,
    principal: Principal = Depends(require_session("actions")),
    runtime: Runtime = Depends(get_runtime),
) -> OkResponse:
    limiter = runtime.accounts.limiter
    key = f"pin-password:{principal.user.id}"
    if limiter.blocked(key, f"ip:{client_ip(request)}"):
        raise HTTPException(429, detail="too many wrong passwords; try again in 15 minutes")
    if not runtime.accounts.check_password(principal.user.id, body.password):
        limiter.fail(key)
        raise HTTPException(403, detail="that is not your password")
    limiter.clear(key)
    runtime.guard.set_pin(
        body.pin, user_id=principal.user.id, actor=principal.actor, channel=principal.channel
    )
    return OkResponse()


# The signed-in user's own sessions. Seeing or ending them needs a session, never a token.


def current_flag(row: dict[str, Any], principal: Principal) -> dict[str, Any]:
    return {**row, "current": row["id"] == principal.credential_id}


def end_session(
    runtime: Runtime, who: Principal, response: Response, session: dict[str, Any]
) -> None:
    """End a session, log it, and drop the cookie if it was the caller's own."""
    if not runtime.accounts.end_session_id(session["id"]):
        raise HTTPException(404, detail="no such session")  # ended in the meantime
    changes.record(
        runtime.store,
        who.actor,
        "session.revoked",
        session["id"],
        before={"user": session["email"]},
    )
    if session["id"] == who.credential_id:
        response.delete_cookie(SESSION_COOKIE, path="/")


@router.get(
    "/me/sessions",
    response_model=list[SessionView],
    summary="Your signed-in sessions, most recently used first",
    responses=_errors(e401="Not signed in", e403="An API token: this needs a session"),
)
def my_sessions(
    principal: Principal = Depends(signed_in), runtime: Runtime = Depends(get_runtime)
) -> list[SessionView]:
    return [
        SessionView(**current_flag(row, principal))
        for row in runtime.accounts.sessions(principal.user.id)
    ]


@router.delete(
    "/me/sessions/{session_id}",
    response_model=OkResponse,
    summary="Sign out one of your sessions (this one too, if you name it)",
    responses=_errors(
        e401="Not signed in",
        e403="An API token, or no CSRF header",
        e404="Not one of your active sessions",
    ),
)
def end_my_session(
    session_id: str,
    response: Response,
    principal: Principal = Depends(signed_in),
    runtime: Runtime = Depends(get_runtime),
) -> OkResponse:
    session = runtime.accounts.get_session(session_id)
    # Someone else's session is "not found", so the answer does not say it exists.
    if session is None or session["user_id"] != principal.user.id:
        raise HTTPException(404, detail="no such session")
    end_session(runtime, principal, response, session)
    return OkResponse()


@router.post(
    "/me/sessions/revoke-others",
    response_model=SessionsEnded,
    summary="Sign out all your other sessions, keeping this one",
    responses=_errors(e401="Not signed in", e403="An API token, or no CSRF header"),
)
def end_my_other_sessions(
    principal: Principal = Depends(signed_in), runtime: Runtime = Depends(get_runtime)
) -> SessionsEnded:
    ended = runtime.accounts.end_other_sessions(principal.user.id, keep=principal.credential_id)
    if ended:
        changes.record(
            runtime.store,
            principal.actor,
            "session.revoked_others",
            principal.user.email,
            after={"ended": ended},
        )
    return SessionsEnded(ended=ended)
