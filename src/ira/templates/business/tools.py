"""This business's tools: what Ira can look up, and what it can change.

REPLACE ME. The two tools below are placeholders, so that the whole flow works
on the first day. They keep notes in ``<data_dir>/notes.db``:

    find_notes(text)   a read tool: Ira calls it freely to look things up
    add_note(text)     an action tool: Ira only proposes it, and it runs once
                       after someone allowed to confirm types their PIN

Replace them with functions over this business's own data: a booking system's
API, a spreadsheet export, a shop database. Keep anything that reads as
``@tool``, and anything that changes data as ``@action`` with a summary that
says exactly what will happen. The clinic example in the IRA repository
(examples/clinic/clinic.py) is a complete set to copy from.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from pydantic import Field

from ira import ToolContext, ToolError, action, tool

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

_db_path: Path | None = None


def setup(ctx: ToolContext) -> None:
    """Called by Ira after import: remember where this business's data lives."""
    global _db_path
    _db_path = ctx.data_dir / "notes.db"


@contextlib.contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """A connection that commits on success and is always closed."""
    if _db_path is None:
        raise ToolError("the tools are not set up")
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        with conn:
            yield conn
    finally:
        conn.close()


# --- REPLACE ME: a read tool ----------------------------------------------------


@tool
def find_notes(
    text: Annotated[str, Field(min_length=2, max_length=100, description="Words to look for")],
) -> list[dict]:
    """Saved notes that contain some words, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, text, created_at FROM notes WHERE text LIKE ? ORDER BY id DESC LIMIT 20",
            (f"%{text.strip()}%",),
        ).fetchall()
    return [dict(row) for row in rows]


# --- REPLACE ME: an action tool ---------------------------------------------------


def _add_note_summary(text: str) -> str:
    # What the person confirming reads on the PIN card. A summary may look
    # things up, and raise ToolError to refuse a proposal that cannot work.
    return f"Save the note: {text.strip()}"


@action(summary=_add_note_summary)
def add_note(
    text: Annotated[str, Field(min_length=2, max_length=500, description="The note to save")],
) -> dict:
    """Save a note. Ira only proposes it; it runs after someone confirms with a PIN."""
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO notes (text, created_at) VALUES (?, ?)",
            (text.strip(), dt.datetime.now().isoformat(timespec="seconds")),
        )
    return {"id": cursor.lastrowid, "saved": text.strip()}
