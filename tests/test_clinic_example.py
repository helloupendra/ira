"""The Sunrise Dental Clinic example, end to end with the no-key demo router."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from ira.models.fake import RouterProvider
from ira.tools.loader import import_tool_module
from ira.tools.registry import ToolContext, ToolError, default_registry

from .conftest import make_runtime

pytestmark = pytest.mark.anyio

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "clinic" / "clinic.py"


@pytest.fixture
def clinic(tmp_path):
    module = import_tool_module(str(EXAMPLE), Path.cwd())
    ctx = ToolContext(data_dir=tmp_path, config_dir=EXAMPLE.parent)
    module.setup(ctx)
    module.seed(ctx)
    return module


def next_open_day() -> dt.date:
    day = dt.date.today() + dt.timedelta(days=1)
    while day.weekday() == 6:
        day += dt.timedelta(days=1)
    return day


def test_read_tools(clinic):
    hours = clinic.clinic_hours()
    assert hours["hours"]["Sunday"] == "closed"
    assert hours["phone"].startswith("555-")

    slots = clinic.find_slots(next_open_day().isoformat())
    assert slots["free"] and all(len(s) == 5 for s in slots["free"])

    upcoming = clinic.list_appointments("Example")
    assert upcoming and all("Example" in a["patient"] for a in upcoming)


def test_booking_validates_the_slot(clinic):
    day = next_open_day()
    free = clinic.find_slots(day.isoformat())["free"][0]
    with pytest.raises(ToolError, match="not an appointment slot"):
        clinic._book_summary("Jamie Example", f"{day} 13:15")
    summary = clinic._book_summary("Jamie Example", f"{day} {free}")
    assert summary.startswith("Book Jamie Example on")
    clinic.book_appointment("Jamie Example", f"{day} {free}")
    with pytest.raises(ToolError, match="already taken"):
        clinic.book_appointment("Someone Else", f"{day} {free}")


def test_demo_data_is_fictional(clinic):
    import sqlite3

    rows = (
        sqlite3.connect(clinic._db_path).execute("SELECT phone, email FROM appointments").fetchall()
    )
    assert rows
    for phone, email in rows:
        assert phone.startswith("555-01")
        assert email.endswith("@example.com")


async def test_demo_router_proposes_and_the_pin_cancels(clinic):
    runtime = make_runtime(provider=RouterProvider(), registry=default_registry)
    runtime.guard.set_pin("2468")
    first = clinic.list_appointments("Avery")[0]

    reply = await runtime.assistant.ask(f"cancel appointment {first['id']}", conversation_id="demo")

    assert reply.action is not None
    assert reply.action.summary.startswith(f"Cancel appointment #{first['id']}: Avery Example")
    assert clinic.list_appointments("Avery")[0]["id"] == first["id"]  # not yet

    outcome = await runtime.guard.confirm(reply.action.id, "2468")
    assert outcome.status == "executed"
    assert first["id"] not in [a["id"] for a in clinic.list_appointments("Avery")]
