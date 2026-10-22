"""What a Mac can be given at pairing, and the events a device may send."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ira.channels.devices import KIND_SKILLS
from ira.channels.http import create_app
from ira.devices.protocol import ProtocolError, parse_event
from ira.devices.store import SKILLS

from .conftest import make_runtime


def test_every_mac_skill_is_offered_and_explained():
    mac = KIND_SKILLS["mac"]
    for skill in ("files", "screen", "browser", "contacts", "calendar", "reminders", "mail"):
        assert skill in mac
    for skill in ("notes", "messages", "apps", "clipboard", "shortcuts", "routine", "tasks"):
        assert skill in mac
    assert "chrome" not in mac and "chrome" not in SKILLS
    assert all(SKILLS.get(skill) for skill in mac), [s for s in mac if not SKILLS.get(s)]


def test_the_skills_route_says_which_devices_offer_them(registry):
    with TestClient(create_app(make_runtime(registry=registry), start_channels=False)) as client:
        assert client.get("/v1/me/skills").status_code == 401  # a person's own, signed in


def test_a_long_task_may_say_how_it_is_going():
    event = parse_event(
        {
            "type": "event",
            "event": "task_progress",
            "title": "Task t1 in shop: 5 minutes in",
            "text": "Running the tests",
        }
    )
    assert event.event == "task_progress" and event.title.startswith("Task t1")
    try:
        parse_event({"type": "event", "event": "task_paused", "title": "x"})
    except ProtocolError:
        pass
    else:
        raise AssertionError("an unknown event must be refused")
