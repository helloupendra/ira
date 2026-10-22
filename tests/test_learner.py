"""The learner: patterns against hand-computed numbers, the proof gate, use, and reminders."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from ira.accounts import Accounts
from ira.channels.http import create_app
from ira.learning.learner import Learner
from ira.learning.patterns import (
    clock,
    duration_patterns,
    find_patterns,
    numbers_ok,
    quartiles,
    time_patterns,
)
from ira.learning.reminders import reminder_tools
from ira.learning.scheduler import LearningScheduler
from ira.learning.service import LearningService
from ira.tools.registry import ToolError
from ira.usersettings import UserSettings

from .conftest import FAST_PIN_ITERATIONS, Clock, make_runtime

pytestmark = pytest.mark.anyio

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
ZONE = ZoneInfo("Asia/Kolkata")
TODAY = dt.date(2026, 10, 23)  # a Friday


def at(day: str, hhmm: str) -> float:
    hours, minutes = (int(x) for x in hhmm.split(":"))
    return (
        dt.datetime.fromisoformat(day).replace(hour=hours, minute=minutes, tzinfo=ZONE).timestamp()
    )


# Nine weekdays over 16 days leaving Office; sorted: 18:10 18:20 18:25 18:30 18:34 18:40
# 18:45 18:50 19:00. Inclusive quartiles: 18:25, 18:34, 18:45; spread 20 minutes.
LEAVES = [
    ("2026-10-05", "18:34"),
    ("2026-10-06", "18:10"),
    ("2026-10-08", "19:00"),
    ("2026-10-09", "18:25"),
    ("2026-10-12", "18:50"),
    ("2026-10-14", "18:20"),
    ("2026-10-15", "18:45"),
    ("2026-10-19", "18:30"),
    ("2026-10-21", "18:40"),
]


def observations(rows, kind="leave", label="Office", source="phone", start=1):
    return [
        {"id": start + i, "at": at(day, hhmm), "kind": kind, "label": label, "source": source}
        for i, (day, hhmm) in enumerate(rows)
    ]


def test_quartiles_and_clock():
    assert quartiles([1.0]) == (1.0, 1.0, 1.0)
    assert quartiles([10, 20, 30, 40, 50]) == (20, 30, 40)
    assert clock(0) == "04:00" and clock(870) == "18:30" and clock(1430) == "03:50"


def test_a_routine_time_matches_the_hand_computed_numbers():
    (pattern,) = time_patterns(observations(LEAVES), ZONE, TODAY)
    assert pattern.key == "leave:Office:weekdays"
    ev = pattern.evidence
    assert (ev["median"], ev["q1"], ev["q3"], ev["spread_minutes"]) == (
        "18:34",
        "18:25",
        "18:45",
        20,
    )
    assert (ev["days"], ev["span_days"], ev["seen"], ev["window"]) == (9, 16, 9, 15)
    assert pattern.text == (
        "You leave Office at about 18:34 on weekdays (most days between 18:25 and 18:45; "
        "seen on 9 of the last 15 weekdays)."
    )
    assert pattern.passes and numbers_ok(pattern.text, ev)
    assert not numbers_ok("You leave Office at about 17:00 on weekdays.", ev)


def test_the_proof_gate_needs_eight_days_two_weeks_and_a_steady_time():
    seven = time_patterns(observations(LEAVES[:7]), ZONE, TODAY)[0]
    assert not seven.passes  # 7 days
    short = time_patterns(observations(LEAVES[1:9]), ZONE, TODAY)[0]
    assert short.evidence["span_days"] == 15 and short.passes  # 8 days over 15
    tight = [(d, t) for d, t in LEAVES if d >= "2026-10-08"] + [("2026-10-20", "18:33")]
    assert time_patterns(observations(tight), ZONE, TODAY)[0].evidence["span_days"] == 13
    assert not time_patterns(observations(tight), ZONE, TODAY)[0].passes
    wide = [(d, f"{16 + i % 5}:00") for i, (d, _) in enumerate(LEAVES)]
    assert not time_patterns(observations(wide), ZONE, TODAY)[0].passes  # spread too wide


def test_a_day_runs_from_four_to_four_and_weekends_are_apart():
    # 00:30 on Sunday and 01:10 on Monday belong to Saturday's and Sunday's days.
    rows = observations([("2026-10-18", "00:30"), ("2026-10-19", "01:10")], kind="leave")
    (pattern,) = time_patterns(rows, ZONE, TODAY)
    assert pattern.key == "leave:Office:weekends"
    assert pattern.evidence["dates"] == ["2026-10-17", "2026-10-18"]
    assert pattern.evidence["times"] == ["00:30", "01:10"]


def test_a_commute_duration():
    days = [
        "2026-10-05",
        "2026-10-06",
        "2026-10-07",
        "2026-10-09",
        "2026-10-12",
        "2026-10-14",
        "2026-10-16",
        "2026-10-20",
    ]
    arrivals = ["09:30", "09:35", "09:40", "09:30", "09:45", "09:35", "09:40", "09:30"]
    rows = observations([(d, "09:00") for d in days], label="Home")
    rows += observations(list(zip(days, arrivals, strict=True)), kind="arrive", start=100)
    (pattern,) = duration_patterns(rows, ZONE)
    ev = pattern.evidence
    assert (ev["median_minutes"], ev["q1_minutes"], ev["q3_minutes"], ev["days"]) == (35, 30, 40, 8)
    assert pattern.text == (
        "Going from Home to Office takes you about 35 minutes "
        "(between 30 and 40 on most of 8 days)."
    )
    assert pattern.passes and numbers_ok(pattern.text, ev)


def test_a_mac_on_a_named_network_is_reaching_and_leaving_it():
    rows = [
        {
            "id": 1,
            "at": at("2026-10-19", "09:12"),
            "kind": "unlock",
            "label": "Office",
            "source": "mac",
        },
        {
            "id": 2,
            "at": at("2026-10-19", "13:00"),
            "kind": "lock",
            "label": "Office",
            "source": "mac",
        },
        {
            "id": 3,
            "at": at("2026-10-19", "18:41"),
            "kind": "sleep",
            "label": "Office",
            "source": "mac",
        },
        {
            "id": 4,
            "at": at("2026-10-19", "22:05"),
            "kind": "lock",
            "label": "Home",
            "source": "mac",
        },
        {
            "id": 5,
            "at": at("2026-10-20", "09:20"),
            "kind": "unlock",
            "label": "Office",
            "source": "mac",
        },
        {
            "id": 6,
            "at": at("2026-10-20", "18:30"),
            "kind": "lock",
            "label": "Office",
            "source": "mac",
        },
    ]
    found = {p.key: p for p in find_patterns(rows, ZONE, TODAY)}
    assert found["arrive:Office:weekdays"].evidence["times"] == ["09:12", "09:20"]
    assert found["leave:Office:weekdays"].evidence["times"] == ["18:41", "18:30"]
    assert found["last_activity:weekdays"].evidence["times"] == ["22:05", "18:30"]


# --- the learner -------------------------------------------------------------------------


def setup(store, clock_value=None):
    clock = Clock(clock_value or at("2026-10-23", "10:00"))
    settings = UserSettings(store)
    told = []

    async def notify(user_id, event):
        told.append((user_id, event.event, event.title, event.text, event.data))

    service = LearningService(store, settings, notify=notify, clock=clock)
    learner = Learner(service, clock=clock)
    user = Accounts(store).create_user("owner@example.com", PASSWORD, "owner")
    settings.set(user.id, "learning", True)
    settings.set(user.id, "timezone", "Asia/Kolkata")
    for row in observations(LEAVES):
        service.data.add(user.id, row["kind"], "phone", at=row["at"], label=row["label"])
    return learner, user, told, clock


async def test_ready_learnings_are_asked_once_then_used_once_approved(store):
    learner, user, told, _ = setup(store)
    (learning,) = await learner.run(user.id)
    assert learning.status == "asked"
    assert len(told) == 1 and told[0][1] == "learning_question"
    assert told[0][2] == "Shall I remember this?"
    assert told[0][3].startswith("You leave Office at about 18:34 on weekdays")
    assert told[0][4] == {"learning_id": learning.id}
    await learner.run(user.id)
    assert len(told) == 1  # asked once
    assert learner.memory(user.id) == []
    learner.approve(user.id, learning.id)
    assert learner.memory(user.id) == [learning.text]
    other = Accounts(store).create_user("staff@example.com", PASSWORD, "staff")
    assert learner.memory(other.id) == []


async def test_rejected_learnings_stay_rejected_and_are_not_asked_again(store):
    learner, user, told, _ = setup(store)
    (learning,) = await learner.run(user.id)
    learner.reject(user.id, learning.id)
    learner.data.add(user.id, "leave", "phone", at=at("2026-10-22", "18:36"), label="Office")
    (again,) = await learner.run(user.id)
    assert again.status == "rejected" and len(told) == 1


async def test_active_learnings_fade_or_change(store):
    learner, user, told, clock = setup(store)
    (learning,) = await learner.run(user.id)
    learner.approve(user.id, learning.id)
    # Five recent weekdays far later than the approved middle half: changed, asked again.
    for day in ("2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"):
        learner.data.add(user.id, "leave", "phone", at=at(day, "20:15"), label="Office")
    clock.now = at("2026-10-31", "10:00")
    (changed,) = await learner.run(user.id)
    assert changed.status == "asked" and len(told) == 2
    assert told[1][2].startswith("This seems to have changed.")
    learner.approve(user.id, changed.id)
    clock.now = at("2026-12-01", "10:00")  # nothing seen for over 21 days
    (faded,) = await learner.run(user.id)
    assert faded.status == "faded" and learner.memory(user.id) == []


async def test_edit_keeps_the_numbers_and_forget_deletes_the_evidence(store):
    learner, user, _, _ = setup(store)
    (learning,) = await learner.run(user.id)
    edited = learner.edit(
        user.id, learning.id, "I head home from the office around 18:34 on workdays"
    )
    assert edited.text.startswith("I head home")
    from ira.learning.store import LearningError

    with pytest.raises(LearningError, match="not in the evidence"):
        learner.edit(user.id, learning.id, "I leave the office at 17:00")
    assert learner.forget(user.id, learning.id) == 9
    assert learner.data.observations(user.id) == [] and learner.data.learnings(user.id) == []


async def test_nudges_come_fifteen_minutes_early_once_and_not_after_it_happened(store):
    learner, user, told, clock = setup(store)
    (learning,) = await learner.run(user.id)
    learner.approve(user.id, learning.id)
    learner.service.user_settings.set(user.id, "nudges", True)
    clock.now = at("2026-10-23", "18:00")
    assert await learner.nudge(user.id) == 0  # 34 minutes early: not yet
    clock.now = at("2026-10-23", "18:22")
    assert await learner.nudge(user.id) == 1
    assert told[-1][1:3] == ("nudge", "18:22: you usually leave Office at about 18:34")
    assert await learner.nudge(user.id) == 0  # once a day
    clock.now = at("2026-10-26", "18:20")  # Monday, but they already left
    learner.data.add(user.id, "leave", "phone", at=at("2026-10-26", "17:50"), label="Office")
    assert await learner.nudge(user.id) == 0


async def test_reminders_by_time_and_by_place(store):
    learner, user, told, clock = setup(store)
    service = learner.service
    remind, listed = reminder_tools(service, user.id, ZONE)
    made = await remind.run({"text": "call the bank", "at": "2026-10-24T09:00"})
    assert made["summary"] == "Reminder set for Saturday 24 October at 09:00: call the bank"
    with pytest.raises(ToolError, match="already passed"):
        await remind.run({"text": "x", "at": "2026-10-20T09:00"})
    with pytest.raises(ToolError, match="don't know a place called Gym"):
        await remind.run({"text": "stretch", "when": "arrive", "place": "Gym"})
    placed = await remind.run({"text": "water the plants", "when": "arrive", "place": "office"})
    assert placed["summary"] == "I'll remind you when you reach Office: water the plants"
    assert len((await listed.run({}))["reminders"]) == 2
    clock.now = at("2026-10-24", "09:00")
    assert await service.fire_due() == 1
    assert told[-1][1:3] == ("reminder", "Reminder: call the bank")
    service.user_settings.set(user.id, "learning_sources", ["phone"])
    await service.from_phone(user.id, "arrive", "Office")
    assert told[-1][2:4] == ("Reminder: water the plants", "You reached Office.")
    assert service.data.reminders(user.id) == []


async def test_the_scheduler_runs_the_learner_once_a_night(store):
    learner, user, told, clock = setup(store, at("2026-10-23", "02:30"))
    scheduler = LearningScheduler(learner, clock=clock)
    await scheduler.tick()
    assert learner.data.learnings(user.id) == []  # before 03:00
    clock.now = at("2026-10-23", "03:05")
    await scheduler.tick()
    assert [item.status for item in learner.data.learnings(user.id)] == ["asked"]
    await scheduler.tick()
    assert len(told) == 1


def test_learnings_over_http_are_the_callers_own(registry):
    runtime = make_runtime(registry=registry)
    runtime.guard.pin_iterations = FAST_PIN_ITERATIONS
    owner = runtime.accounts.create_user("owner@example.com", PASSWORD, "owner")
    runtime.accounts.create_user("staff@example.com", PASSWORD, "staff")
    settings = runtime.assistant.user_settings
    settings.set(owner.id, "learning", True)
    settings.set(owner.id, "timezone", "Asia/Kolkata")
    for row in observations(LEAVES):
        runtime.learning.data.add(owner.id, "leave", "phone", at=row["at"], label="Office")

    def login(client, email):
        r = client.post(
            "/v1/auth/login", json={"email": email, "password": PASSWORD, "use_cookie": False}
        )
        return {"Authorization": f"Bearer {r.json()['session_token']}"}

    with TestClient(create_app(runtime, start_channels=False)) as client:
        mine, theirs = login(client, "owner@example.com"), login(client, "staff@example.com")
        view = client.post("/v1/me/learning/refresh", headers=mine).json()
        (item,) = view["learnings"]
        assert item["status"] == "asked" and item["evidence"]["median"] == "18:34"
        assert (
            client.post(f"/v1/me/learnings/{item['id']}/approve", headers=theirs).status_code == 404
        )
        assert client.get("/v1/me/learning", headers=theirs).json()["learnings"] == []
        done = client.post(f"/v1/me/learnings/{item['id']}/approve", headers=mine).json()
        assert done["status"] == "active"
        bad = client.patch(
            f"/v1/me/learnings/{item['id']}", json={"text": "I leave at 17:00"}, headers=mine
        )
        assert bad.status_code == 400
        assert (
            client.patch(
                "/v1/me/settings", json={"timezone": "Mars/Olympus"}, headers=mine
            ).status_code
            == 400
        )
        assert (
            client.patch("/v1/me/settings", json={"timezone": "Asia/Kolkata"}, headers=mine).json()[
                "timezone"
            ]
            == "Asia/Kolkata"
        )
        prompt = runtime.assistant.system_prompt(owner.id)
        assert "told you or approved" in prompt and "18:34" in prompt
        assert client.delete(f"/v1/me/learnings/{item['id']}", headers=mine).json() == {
            "observations": 9
        }


async def test_people_the_person_names_are_remembered_and_used(store):
    from ira.learning.people import people_tools

    learner, user, _, _ = setup(store)
    learner.service.user_settings.set(user.id, "learning", None)  # no switch needed
    remember, forget = people_tools(learner.data, user.id)
    assert remember.tier == 1 and forget.tier == 1
    done = await remember.run({"name": "Rahul Sharma", "about": "my CA, files the GST"})
    assert done == {"summary": "I'll remember: Rahul Sharma: my CA, files the GST"}
    await remember.run({"name": "rahul  sharma", "about": "my CA"})  # the same person, updated
    assert learner.memory(user.id) == ["rahul sharma: my CA"]
    with pytest.raises(ToolError, match="say who it is"):
        await remember.run({"name": "Priya", "about": " "})
    other = Accounts(store).create_user("staff@example.com", PASSWORD, "staff")
    assert learner.memory(other.id) == []
    assert (await forget.run({"name": "Rahul Sharma"}))["summary"].startswith("Forgotten")
    assert learner.memory(user.id) == []
    assert (await forget.run({"name": "Nobody"}))["summary"] == "I had nothing saved about Nobody."


def test_the_prompt_asks_to_chain_tools_and_ask_back(registry):
    runtime = make_runtime(registry=registry)
    prompt = runtime.assistant.system_prompt(None)
    assert "several tools in a row" in prompt
    assert "ask which one and name the choices" in prompt
