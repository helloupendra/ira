"""First-run setup: the first owner account, guarded by a one-time code.

The setup routes are public: they carry their own secret, the code printed by
``ira serve``, and they sign the new owner in with the session cookie.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ira import __version__, changes
from ira.accounts import AccountError
from ira.channels.deps import client_ip, get_runtime, start_browser_session
from ira.channels.schemas import SessionResponse, SetupOwnerRequest, SetupStatus
from ira.runtime import Runtime

router = APIRouter(prefix="/v1", tags=["setup"])


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
)
def setup_owner(
    body: SetupOwnerRequest,
    request: Request,
    response: Response,
    runtime: Runtime = Depends(get_runtime),
) -> SessionResponse:
    return claim_setup(runtime, request, response, body.code, body.email, body.password)
