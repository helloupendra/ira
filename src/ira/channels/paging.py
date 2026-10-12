"""Paged lists: each one fetches a row more than it returns, to say whether more follow.

A paged list stays a JSON array, so older clients keep working; whether
another page exists travels in the ``X-Has-More`` response header.
"""

from __future__ import annotations

from typing import Any, TypeVar

from fastapi import Response

T = TypeVar("T")

HAS_MORE = "X-Has-More"

HAS_MORE_HEADER: dict[str, Any] = {
    HAS_MORE: {
        "description": "true when more rows follow this page (ask again with the cursor from "
        "the last row), false when this page is the last.",
        "schema": {"type": "string", "enum": ["true", "false"]},
    }
}

# For a route's ``responses``: documents the header on the 200 answer.
PAGED: dict[int | str, dict[str, Any]] = {
    200: {"description": "One page, newest first", "headers": HAS_MORE_HEADER}
}


def page(rows: list[T], limit: int, response: Response) -> list[T]:
    """Cut a ``limit + 1`` fetch to ``limit`` rows and set ``X-Has-More``."""
    response.headers[HAS_MORE] = "true" if len(rows) > limit else "false"
    return rows[:limit]
