"""An iPhone as a device: what it may be given, pairing it, and older databases."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from ira.accounts import Accounts
from ira.channels.devices import KIND_SKILLS
from ira.channels.http import create_app
from ira.devices import Devices
from ira.devices.protocol import KINDS, parse_hello
from ira.devices.store import SKILLS
from ira.store import SCHEMA, Store

from .conftest import FAST_PIN_ITERATIONS, make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
PIN = "4321"

# The tools Ira for iPhone offers, as its hello lists them.
IPHONE_TOOLS = [
    {"name": "contacts_lookup", "description": "Find people.", "skill": "contacts", "tier": 0},
    {"name": "calendar_read", "description": "Read events.", "skill": "calendar", "tier": 0},
    {"name": "calendar_add", "description": "Add an event.", "skill": "calendar", "tier": 2},
    {"name": "reminders_list", "description": "List reminders.", "skill": "reminders", "tier": 0},
    {"name": "reminders_add", "description": "Add one.", "skill": "reminders", "tier": 1},
    {"name": "reminders_done", "description": "Mark one done.", "skill": "reminders", "tier": 1},
    {"name": "location_now", "description": "Where it is.", "skill": "location", "tier": 0},
    {"name": "call_place", "description": "Start a call.", "skill": "calls", "tier": 2},
]


def test_an_iphone_is_offered_only_what_ios_allows():
    assert "ios" in KINDS
    iphone = KIND_SKILLS["ios"]
    assert set(iphone) == {"contacts", "calendar", "reminders", "location", "calls"}
    # iOS lets no app read the call log, SMS or other apps' notifications.
    for skill in ("messages", "notifications", "screen", "files"):
        assert skill not in iphone
    assert all(SKILLS.get(skill) for skill in iphone)
    assert "Android" in SKILLS["calls"]  # "who called" is Android's alone


def test_an_iphone_pairs_says_hello_and_lists_its_skills(registry):
    runtime = make_runtime(registry=registry)
    runtime.guard.pin_iterations = FAST_PIN_ITERATIONS
    owner = Accounts(runtime.store).create_user("owner@example.com", PASSWORD, "owner")
    runtime.guard.set_pin(PIN, user_id=owner.id, actor=owner.email)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        login = client.post(
            "/v1/auth/login",
            json={"email": "owner@example.com", "password": PASSWORD, "use_cookie": False},
        )
        mine = {"Authorization": f"Bearer {login.json()['session_token']}"}
        offered = {s["name"]: s["kinds"] for s in client.get("/v1/me/skills", headers=mine).json()}
        assert "ios" in offered["location"] and "ios" not in offered["files"]

        body = {"kind": "ios", "label": None, "skills": ["contacts", "location"], "pin": PIN}
        made = client.post("/v1/me/devices/pairing", json=body, headers=mine)
        assert made.status_code == 200, made.text
        assert made.json()["label"] == "My iPhone"
        as_a_mac = {"code": made.json()["code"], "kind": "mac"}
        assert client.post("/v1/devices/pair", json=as_a_mac).status_code == 410
        made = client.post("/v1/me/devices/pairing", json=body, headers=mine).json()
        done = client.post(
            "/v1/devices/pair",
            json={"code": made["code"], "kind": "ios"},
            headers={"User-Agent": "ira-ios/0.1.0"},
        )
        assert done.status_code == 200, done.text
        token = done.json()["token"]
        assert done.json()["kind"] == "ios"

        hello = {"type": "hello", "kind": "ios", "label": "My iPhone", "version": "0.1.0"}
        with client.websocket_connect(
            "/v1/devices/ws", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            ws.send_json({**hello, "tools": IPHONE_TOOLS})
            welcome = ws.receive_json()
            assert welcome["type"] == "welcome"
            assert sorted(welcome["skills"]) == ["contacts", "location"]

        listed = client.get("/v1/me/devices", headers=mine).json()
        phone = next(d for d in listed if d["kind"] == "ios")
        assert [s["name"] for s in phone["skills"]] == list(KIND_SKILLS["ios"])
        tiers = {t["name"]: t["tier"] for t in phone["tools"]}
        assert tiers["call_place"] == 2 and tiers["location_now"] == 0


def test_the_hello_keeps_the_iphones_tiers():
    hello = {"type": "hello", "kind": "ios", "label": "iPhone", "version": "0.1.0"}
    parsed = parse_hello({**hello, "tools": IPHONE_TOOLS}, "ios")
    assert {t.name: (t.skill, t.tier) for t in parsed.tools}["calendar_add"] == ("calendar", 2)


def test_a_database_from_before_iphones_takes_one_and_keeps_its_devices(tmp_path):
    # The schema as it was: the same tables, with a devices CHECK that knew two kinds.
    path = tmp_path / "ira.db"
    old = sqlite3.connect(path)
    old.executescript(SCHEMA.replace("('mac', 'android', 'ios')", "('mac', 'android')"))
    for label, kind in (("Office Mac", "mac"), ("Pixel", "android")):
        old.execute(
            "INSERT INTO devices (user_id, kind, label, token_hash, created_at) "
            "VALUES (1, ?, ?, ?, 1.0)",
            (kind, label, f"hash-{kind}"),
        )
    old.execute("DELETE FROM devices WHERE kind = 'android'")
    old.commit()
    old.close()

    store = Store(path)
    owner = Accounts(store).create_user("owner@example.com", PASSWORD, "owner")
    rows = store.query("SELECT id, kind, label, token_hash FROM devices")
    assert [tuple(r) for r in rows] == [(1, "mac", "Office Mac", "hash-mac")]
    indexes = store.query("SELECT name FROM sqlite_master WHERE type = 'index'")
    assert "devices_user" in {r["name"] for r in indexes}
    code, _ = Devices(store).start_pairing(owner.id, "ios", None, ["contacts"])
    token, device = Devices(store).redeem(code, "ios")
    assert device.kind == "ios" and device.label == "My iPhone"
    assert device.id == 3  # the removed Android phone's id is never reused
    assert token.startswith("irad_")

    again = Store(path)  # opening it again changes nothing
    assert [r["id"] for r in again.query("SELECT id FROM devices ORDER BY id")] == [1, 3]
