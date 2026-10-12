"""Authentication and permission checks shared by every HTTP route.

A request authenticates with ``Authorization: Bearer <token>`` (an API token
or a session token), or with the HTTP-only session cookie set at sign-in.
Cookie-authenticated requests that change something must also carry an
``X-Ira-Request: 1`` header. Browsers will not add a custom header to a
cross-site request without a CORS preflight, which this API never grants, so
the header blocks cross-site request forgery.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ira.accounts import Principal
from ira.runtime import Runtime

SESSION_COOKIE = "ira_session"
CSRF_HEADER = "x-ira-request"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

bearer_scheme = HTTPBearer(auto_error=False, description="An API token or a session token.")


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def _unauthorized(detail: str = "sign in or send a bearer token") -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def get_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    runtime: Runtime = Depends(get_runtime),
) -> Principal:
    if credentials is not None:
        principal = runtime.accounts.principal(credentials.credentials)
        if principal is None:
            raise _unauthorized("invalid or revoked token")
        return principal
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        principal = runtime.accounts.session_principal(cookie)
        if principal is None:
            raise _unauthorized("session expired; sign in again")
        if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="missing X-Ira-Request header")
        return principal
    raise _unauthorized()


def require(permission: str) -> Callable[..., Awaitable[Principal]]:
    async def check(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.can(permission):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, detail=f"this credential lacks '{permission}'"
            )
        return principal

    check.__name__ = f"require_{permission.replace('.', '_')}"
    return check
