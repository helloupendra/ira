"""A request body stopped at a limit as it arrives, rather than read whole and then measured."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request


def limit_body(request: Request, limit: int, too_big: str = "that is too large") -> None:
    """Refuse a declared length past `limit` now, and stop a chunked one when it gets there."""
    declared = request.headers.get("content-length") or ""
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, detail=too_big)
    receive = request.receive
    seen = 0

    async def counted() -> Any:
        nonlocal seen
        message = await receive()
        if message.get("type") == "http.request":
            seen += len(message.get("body", b""))
            if seen > limit:
                raise HTTPException(413, detail=too_big)
        return message

    request._receive = counted
