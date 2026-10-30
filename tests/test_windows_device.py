"""A Windows PC as a device: what it may be given, pairing it, its events, older databases,
and the Windows programs Ira never acts in."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from ira.accounts import Accounts
from ira.approvals import never_app
from ira.channels.devices import KIND_SKILLS
from ira.channels.http import create_app
from ira.devices import Devices
from ira.devices.protocol import KINDS
from ira.devices.store import SKILLS
from ira.store import SCHEMA, Store

from .conftest import FAST_PIN_ITERATIONS, make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
PIN = "4321"

# The tools Ira for Windows offers, as its hello lists them.
WINDOWS_TOOLS = [
    {"name": "files_find", "description": "Find files.", "skill": "files", "tier": 0},
    {"name": "file_read", "description": "Read one file.", "skill": "files", "tier": 0},
    {"name": "screen_read", "description": "Read the front window.", "skill": "screen", "tier": 0},
    {"name": "app_open", "description": "Open an app.", "skill": "apps", "tier": 1},
]


def test_a_windows_pc_is_offered_what_a_pc_can_do():
    assert "windows" in KINDS
    pc = KIND_SKILLS["windows"]
    assert set(pc) == {"files", "screen", "browser", "apps", "clipboard", "control", "routine"}
    # Calls, texts and location belong to phones; calendar and mail come from accounts.
    for skill in ("calls", "messages", "location", "calendar", "mail"):
        assert skill not in pc
    assert all(SKILLS.get(skill) for skill in pc)


def test_a_windows_pc_pairs_says_hello_and_hears_events(registry):
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
        assert "windows" in offered["screen"] and "windows" not in offered["calls"]

        body = {"kind": "windows", "label": None, "skills": ["files", "screen"], "pin": PIN}
        made = client.post("/v1/me/devices/pairing", json=body, headers=mine)
        assert made.status_code == 200, made.text
        assert made.json()["label"] == "My Windows PC"
        as_a_mac = {"code": made.json()["code"], "kind": "mac"}
        assert client.post("/v1/devices/pair", json=as_a_mac).status_code == 410
        made = client.post("/v1/me/devices/pairing", json=body, headers=mine).json()
        done = client.post("/v1/devices/pair", json={"code": made["code"], "kind": "windows"})
        assert done.status_code == 200, done.text
        assert done.json()["kind"] == "windows"
        token = done.json()["token"]

        hello = {"type": "hello", "kind": "windows", "label": "Office PC", "version": "0.1.0"}
        with client.websocket_connect(
            "/v1/devices/ws", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            ws.send_json({**hello, "tools": WINDOWS_TOOLS})
            welcome = ws.receive_json()
            assert welcome["type"] == "welcome"
            assert sorted(welcome["skills"]) == ["files", "screen"]
            # A Windows PC shows its person's events itself, as a notification.
            ws.send_json(
                {"type": "event", "event": "task_done", "title": "Done", "text": "All good."}
            )
            heard = ws.receive_json()
            while heard["type"] in ("ping", "pong", "skills"):
                heard = ws.receive_json()
            assert (heard["type"], heard["title"]) == ("event", "Done")

        listed = client.get("/v1/me/devices", headers=mine).json()
        pc = next(d for d in listed if d["kind"] == "windows")
        assert [s["name"] for s in pc["skills"]] == list(KIND_SKILLS["windows"])
        assert {t["name"]: t["tier"] for t in pc["tools"]}["app_open"] == 1


def test_a_database_from_before_windows_takes_one_and_keeps_its_devices(tmp_path):
    today = "('mac', 'android', 'ios', 'windows')"
    assert today in SCHEMA
    path = tmp_path / "ira.db"
    old = sqlite3.connect(path)
    old.executescript(SCHEMA.replace(today, "('mac', 'android', 'ios')"))
    old.execute(
        "INSERT INTO devices (user_id, kind, label, token_hash, created_at) "
        "VALUES (1, 'ios', 'My iPhone', 'hash-ios', 1.0)"
    )
    old.commit()
    old.close()

    store = Store(path)
    owner = Accounts(store).create_user("owner@example.com", PASSWORD, "owner")
    rows = store.query("SELECT id, kind, label FROM devices")
    assert [tuple(r) for r in rows] == [(1, "ios", "My iPhone")]
    code, _ = Devices(store).start_pairing(owner.id, "windows", None, ["files"])
    token, device = Devices(store).redeem(code, "windows")
    assert (device.kind, device.label, device.id) == ("windows", "My Windows PC", 2)
    assert token.startswith("irad_")

    created = store.one("SELECT sql FROM sqlite_master WHERE name = 'devices'")["sql"]
    Store(path)  # opening it again leaves the table as it is
    again = Store(path).one("SELECT sql FROM sqlite_master WHERE name = 'devices'")["sql"]
    assert created == again and "'windows'" in again


@pytest.mark.parametrize(
    "app",
    ["cmd.exe", "CMD", "Command Prompt", "PowerShell", "Windows PowerShell", "pwsh.exe",
     "WindowsTerminal.exe", "wt.exe", "Windows Terminal", "wsl.exe", "Registry Editor",
     "regedit.exe", "mmc.exe"],
)  # fmt: skip
def test_windows_shells_are_never_acted_in(app):
    assert never_app(app)


@pytest.mark.parametrize("app", ["Notepad", "notepad.exe", "chrome.exe", "Microsoft Edge", "Excel"])
def test_everyday_windows_apps_are_not_refused(app):
    assert not never_app(app)
