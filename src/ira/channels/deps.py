"""Authentication and permission checks shared by every HTTP route.

A request authenticates with ``Authorization: Bearer <token>`` (an API token
or a session token), or with the HTTP-only session cookie set at sign-in.

Cookie-authenticated requests that change something are checked three ways
against cross-site request forgery:

1. the cookie is ``SameSite=Strict``, so other sites' pages do not send it;
2. the request must carry ``X-Ira-Request: 1``. Browsers will not add a custom
   header to a cross-site request without a CORS preflight, which this API
   never grants;
3. when the browser says where the request came from (``Origin``, or
   ``Sec-Fetch-Site``), it must be this server.

Console writes also need a session: an API token can never change settings
or accounts, whatever its scopes.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ira.accounts import Principal
from ira.channels.schemas import SessionResponse, UserView
from ira.runtime import Runtime

SESSION_COOKIE = "ira_session"
CSRF_HEADER = "x-ira-request"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
COOKIE_SAMESITE = "strict"

bearer_scheme = HTTPBearer(auto_error=False, description="An API token or a session token.")


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def set_session_cookie(response: Response, request: Request, token: str, expires: float) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(expires - time.time()),
        httponly=True,
        samesite=COOKIE_SAMESITE,
        secure=request.url.scheme == "https",
        path="/",
    )


def session_body(
    principal: Principal, expires_at: float | None, token: str | None = None
) -> SessionResponse:
    return SessionResponse(
        user=UserView(**principal.user.public()),
        permissions=sorted(principal.permissions),
        expires_at=expires_at,
        session_token=token,
    )


def start_browser_session(
    runtime: Runtime, request: Request, response: Response, user_id: int
) -> SessionResponse:
    """Sign a user in with the session cookie and return what /v1/auth/me would."""
    user = runtime.accounts.get_user(user_id)
    assert user is not None
    token, expires = runtime.accounts.start_session(
        user, user_agent=request.headers.get("user-agent")
    )
    set_session_cookie(response, request, token, expires)
    principal = runtime.accounts.session_principal(token)
    assert principal is not None
    return session_body(principal, expires)


def _unauthorized(detail: str = "sign in or send a bearer token") -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


# What a paired device may do for its person over HTTP: talk to Ira (typed or by voice) and
# confirm actions. Never settings, accounts or anything an admin does: those need a session.
DEVICE_PERMISSIONS = frozenset({"ask", "voice", "actions"})


def device_principal(runtime: Runtime, token: str) -> Principal | None:
    """The person a device token speaks for, with at most DEVICE_PERMISSIONS of theirs."""
    from ira.devices.store import TOKEN_PREFIX

    if not token.startswith(TOKEN_PREFIX) or runtime.hub is None:
        return None
    device = runtime.hub.devices.by_token(token)
    if device is None:
        return None
    user = runtime.accounts.get_user(device.user_id)
    if user is None:
        return None
    allowed = frozenset(user.permissions) & DEVICE_PERMISSIONS
    return Principal(user, "device", allowed, f"device:{device.id}")


async def get_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    runtime: Runtime = Depends(get_runtime),
) -> Principal:
    if credentials is not None:
        principal = runtime.accounts.principal(credentials.credentials) or device_principal(
            runtime, credentials.credentials
        )
        if principal is None:
            raise _unauthorized("invalid or revoked token")
        return principal
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        principal = runtime.accounts.session_principal(cookie)
        if principal is None:
            raise _unauthorized("session expired; sign in again")
        if request.method not in SAFE_METHODS:
            check_same_origin(request)
        return principal
    raise _unauthorized()


def check_same_origin(request: Request) -> None:
    """Refuse a state-changing browser request that did not come from this server."""
    if request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="missing X-Ira-Request header")
    if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="cross-site request refused")
    origin = request.headers.get("origin")
    if origin is None:
        return
    hosts = {request.headers.get("host", "")}
    # Behind a proxy that rewrites Host, the original arrives as X-Forwarded-Host.
    # A cross-site page cannot set it: custom headers need a preflight we never grant.
    hosts.update(h.strip() for h in request.headers.get("x-forwarded-host", "").split(","))
    if urlsplit(origin).netloc.lower() not in {h.lower() for h in hosts if h}:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="cross-origin request refused (behind a proxy? pass the Host header through)",
        )


def require(permission: str) -> Callable[..., Awaitable[Principal]]:
    async def check(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.can(permission):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, detail=f"this credential lacks '{permission}'"
            )
        return principal

    check.__name__ = f"require_{permission.replace('.', '_')}"
    return check


def require_session(permission: str | None = None) -> Callable[..., Awaitable[Principal]]:
    """A signed-in person, with ``permission`` if one is named.

    API tokens are refused, whatever their scopes.
    """

    async def check(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.via != "session":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="this needs a signed-in session; API tokens cannot change settings "
                "or see sessions",
            )
        if permission is not None and not principal.can(permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f"your role lacks '{permission}'")
        return principal

    suffix = f"_{permission.replace('.', '_')}" if permission else ""
    check.__name__ = f"require_session{suffix}"
    return check
