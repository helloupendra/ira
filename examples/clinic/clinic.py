"""Sunrise Dental Clinic: a fictional practice used to show how Ira's tools work.

Everything here is invented: the clinic, its address, the patients, the
555-01xx phone numbers and the example.com emails. Data lives in
``<data_dir>/clinic.db`` and is created by ``ira demo seed``.

Read tools (Ira calls these freely):
    clinic_hours(), find_slots(date), list_appointments(name)

Action tools (Ira only proposes; the owner confirms with the PIN):
    book_appointment(name, slot), cancel_appointment(id)
"""

from __future__ import annotations

import contextlib
import datetime as dt
import random
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from pydantic import Field

from ira import ToolContext, ToolError, action, tool

CLINIC = "Sunrise Dental Clinic"
SLOT_MINUTES = 30
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
# (open, close) per weekday, Monday = 0. Weekdays close for lunch 13:00-14:00.
HOURS: dict[int, tuple[str, str] | None] = {
    0: ("09:00", "17:00"),
    1: ("09:00", "17:00"),
    2: ("09:00", "17:00"),
    3: ("09:00", "17:00"),
    4: ("09:00", "17:00"),
    5: ("09:00", "13:00"),
    6: None,
}
LUNCH = ("13:00", "14:00")

SCHEMA = """
CREATE TABLE IF NOT EXISTS appointments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    patient    TEXT NOT NULL,
    phone      TEXT NOT NULL,
    email      TEXT NOT NULL,
    starts_at  TEXT NOT NULL,          -- 'YYYY-MM-DD HH:MM', clinic local time
    reason     TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'booked',
    created_at TEXT NOT NULL
);
"""

_db_path: Path | None = None


def setup(ctx: ToolContext) -> None:
    """Called by Ira after import: remember where the data lives."""
    global _db_path
    _db_path = ctx.data_dir / "clinic.db"


@contextlib.contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """A connection that commits on success and is always closed."""
    if _db_path is None:
        raise ToolError("the clinic tools are not set up")
    if not _db_path.exists():
        raise ToolError("there is no clinic data yet; run `ira demo seed`")
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _now() -> dt.datetime:
    return dt.datetime.now().replace(second=0, microsecond=0)


def _parse_day(text: str) -> dt.date:
    value = text.strip().lower()
    today = _now().date()
    if value == "today":
        return today
    if value == "tomorrow":
        return today + dt.timedelta(days=1)
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ToolError("use a date like 2026-10-14, or 'today' or 'tomorrow'") from None


def _parse_slot(text: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(text.strip().replace("T", " "))
    except ValueError:
        raise ToolError("use a slot like '2026-10-14 09:30'") from None


def _clock(day: dt.date, hhmm: str) -> dt.datetime:
    hour, minute = map(int, hhmm.split(":"))
    return dt.datetime.combine(day, dt.time(hour, minute))


def _day_slots(day: dt.date) -> list[dt.datetime]:
    hours = HOURS[day.weekday()]
    if hours is None:
        return []
    start, end = _clock(day, hours[0]), _clock(day, hours[1])
    lunch_start, lunch_end = _clock(day, LUNCH[0]), _clock(day, LUNCH[1])
    slots, current = [], start
    while current < end:
        if not (lunch_start <= current < lunch_end):
            slots.append(current)
        current += dt.timedelta(minutes=SLOT_MINUTES)
    return slots


def _booked(conn: sqlite3.Connection, day: dt.date) -> set[str]:
    rows = conn.execute(
        "SELECT starts_at FROM appointments WHERE status = 'booked' AND starts_at LIKE ?",
        (f"{day.isoformat()}%",),
    ).fetchall()
    return {row["starts_at"] for row in rows}


def _spoken(when: dt.datetime) -> str:
    return f"{WEEKDAYS[when.weekday()]} {when.day} {when:%B} at {when:%H:%M}"


def _check_free(conn: sqlite3.Connection, slot: dt.datetime) -> None:
    if slot not in _day_slots(slot.date()):
        raise ToolError(f"{slot:%Y-%m-%d %H:%M} is not an appointment slot; use find_slots")
    if slot <= _now():
        raise ToolError("that slot is in the past")
    if f"{slot:%Y-%m-%d %H:%M}" in _booked(conn, slot.date()):
        raise ToolError("that slot is already taken; use find_slots for free ones")


# --- read tools ------------------------------------------------------------------


@tool
def clinic_hours() -> dict:
    """Opening hours for each day of the week, plus the clinic's phone and address."""
    hours = {}
    for index, name in enumerate(WEEKDAYS):
        span = HOURS[index]
        if span is None:
            hours[name] = "closed"
        elif index < 5:
            hours[name] = f"{span[0]}-{span[1]} (closed {LUNCH[0]}-{LUNCH[1]} for lunch)"
        else:
            hours[name] = f"{span[0]}-{span[1]}"
    return {
        "clinic": CLINIC,
        "phone": "555-0100",
        "address": "12 Example Street, Springfield",
        "hours": hours,
    }


@tool
def find_slots(
    date: Annotated[str, Field(description="Day to search: YYYY-MM-DD, 'today' or 'tomorrow'")],
) -> dict:
    """Free 30-minute appointment slots on one day."""
    day = _parse_day(date)
    slots = _day_slots(day)
    if not slots:
        return {"date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()], "closed": True}
    with _connect() as conn:
        booked = _booked(conn, day)
    now = _now()
    free = [s.strftime("%H:%M") for s in slots if f"{s:%Y-%m-%d %H:%M}" not in booked and s > now]
    return {"date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()], "free": free}


@tool
def list_appointments(
    name: Annotated[str, Field(min_length=2, description="Patient name, or part of it")],
) -> list[dict]:
    """Upcoming booked appointments for a patient."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, patient, starts_at, reason FROM appointments "
            "WHERE status = 'booked' AND patient LIKE ? AND starts_at >= ? ORDER BY starts_at",
            (f"%{name.strip()}%", f"{_now():%Y-%m-%d %H:%M}"),
        ).fetchall()
    return [
        {"id": r["id"], "patient": r["patient"], "when": r["starts_at"], "reason": r["reason"]}
        for r in rows
    ]


# --- action tools ------------------------------------------------------------------


def _book_summary(name: str, slot: str) -> str:
    when = _parse_slot(slot)
    with _connect() as conn:
        _check_free(conn, when)
    return f"Book {name.strip()} on {_spoken(when)}"


@action(summary=_book_summary)
def book_appointment(
    name: Annotated[str, Field(min_length=2, max_length=80, description="Patient's full name")],
    slot: Annotated[str, Field(description="'YYYY-MM-DD HH:MM', a free slot from find_slots")],
) -> dict:
    """Book an appointment. Ira only proposes it; it runs after the owner's PIN."""
    when = _parse_slot(slot)
    with _connect() as conn:
        _check_free(conn, when)  # check again: the slot may have gone since the proposal
        cursor = conn.execute(
            "INSERT INTO appointments (patient, phone, email, starts_at, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                name.strip(),
                "555-0199",
                "front-desk@example.com",
                f"{when:%Y-%m-%d %H:%M}",
                "booked by phone",
                f"{_now():%Y-%m-%d %H:%M}",
            ),
        )
    return {"id": cursor.lastrowid, "patient": name.strip(), "when": f"{when:%Y-%m-%d %H:%M}"}


def _cancel_summary(id: int) -> str:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (id,)).fetchone()
    if row is None:
        raise ToolError(f"there is no appointment #{id}")
    if row["status"] != "booked":
        raise ToolError(f"appointment #{id} is already {row['status']}")
    return f"Cancel appointment #{id}: {row['patient']} on {_spoken(_parse_slot(row['starts_at']))}"


@action(summary=_cancel_summary)
def cancel_appointment(
    id: Annotated[int, Field(ge=1, description="Appointment id from list_appointments")],
) -> dict:
    """Cancel an appointment. Ira only proposes it; it runs after the owner's PIN."""
    with _connect() as conn:
        changed = conn.execute(
            "UPDATE appointments SET status = 'cancelled' WHERE id = ? AND status = 'booked'",
            (id,),
        ).rowcount
    if changed != 1:
        raise ToolError(f"appointment #{id} could not be cancelled")
    return {"id": id, "status": "cancelled"}


# --- demo data -----------------------------------------------------------------------

PATIENTS = [
    ("Avery Example", "check-up"),
    ("Jordan Sample", "cleaning"),
    ("Riley Demo", "filling"),
    ("Casey Placeholder", "check-up"),
    ("Morgan Fictional", "whitening consultation"),
    ("Taylor Testcase", "cleaning"),
    ("Quinn Madeup", "tooth sensitivity"),
    ("Drew Notreal", "check-up"),
]


def seed(ctx: ToolContext) -> str:
    """Called by `ira demo seed`: recreate the demo appointments for the coming week."""
    setup(ctx)
    assert _db_path is not None
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)  # same demo every time
    with contextlib.closing(sqlite3.connect(_db_path)) as conn, conn:
        conn.executescript(SCHEMA)
        conn.execute("DELETE FROM appointments")
        day, made = _now().date(), 0
        for _ in range(8):
            day += dt.timedelta(days=1)
            slots = _day_slots(day)
            for slot in rng.sample(slots, k=min(len(slots), rng.randint(2, 4))):
                patient, reason = PATIENTS[made % len(PATIENTS)]
                handle = patient.lower().replace(" ", ".")
                conn.execute(
                    "INSERT INTO appointments "
                    "(patient, phone, email, starts_at, reason, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        patient,
                        f"555-01{10 + made % 80:02d}",
                        f"{handle}@example.com",
                        f"{slot:%Y-%m-%d %H:%M}",
                        reason,
                        f"{_now():%Y-%m-%d %H:%M}",
                    ),
                )
                made += 1
    return f"seeded {made} fictional appointments into {_db_path}"
