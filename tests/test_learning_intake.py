"""Learning's intake: consent first, places not coordinates, networks by hash, per person."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.devices import DeviceHub, Devices
from ira.learning.service import LearningService
from ira.learning.store import LearningError, LearningStore, clean_label
from ira.usersettings import UserSettings

from .conftest import FAST_PIN_ITERATIONS, Clock, make_runtime
from .test_devices import connect, paired

pytestmark = pytest.mark.anyio

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
PIN = "4321"
OFFICE = "a1b2c3d4e5f60718"  # pragma: allowlist secret
HOME = "0f1e2d3c4b5a6978"  # pragma: allowlist secret


def signed_in(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/v1/auth/login", json={"email": email, "password": PASSWORD, "use_cookie": False}
    )
    return {"Authorization": f"Bearer {response.json()['session_token']}"}


@pytest.fixture
def runtime(registry):
    runtime = make_runtime(registry=registry)
    runtime.guard.pin_iterations = FAST_PIN_ITERATIONS
    for email, role in (("owner@example.com", "owner"), ("staff@example.com", "staff")):
        user = runtime.accounts.create_user(email, PASSWORD, role)
        runtime.guard.set_pin(PIN, user_id=user.id, actor=email)
    return runtime


def test_labels_are_names_never_coordinates():
    assert clean_label("  Office  ") == "Office"
    for bad in ("28.6139, 77.2090", "12.97 77.59", ""):
        with pytest.raises(LearningError):
            clean_label(bad)


def test_nothing_is_noticed_until_switched_on_with_the_pin(runtime):
    with TestClient(create_app(runtime, start_channels=False)) as client:
        mine = signed_in(client, "owner@example.com")
        view = client.get("/v1/me/learning", headers=mine).json()
        assert view["on"] is False and all(not s["on"] for s in view["sources"])
        before = client.post(
            "/v1/observations", json={"event": "arrive", "place": "Office"}, headers=mine
        )
        assert before.json() == {"recorded": False}

        no_pin = client.patch(
            "/v1/me/learning", json={"on": True, "sources": ["phone"]}, headers=mine
        )
        assert no_pin.status_code == 403
        on = client.patch(
            "/v1/me/learning", json={"on": True, "sources": ["phone"], "pin": PIN}, headers=mine
        )
        assert on.status_code == 200 and on.json()["on"] is True
        kept = client.post(
            "/v1/observations", json={"event": "arrive", "place": "Office"}, headers=mine
        )
        assert kept.json() == {"recorded": True}
        # Switching off never needs the PIN, and stops it at once.
        off = client.patch("/v1/me/learning", json={"sources": []}, headers=mine)
        assert off.status_code == 200
        again = client.post(
            "/v1/observations", json={"event": "leave", "place": "Office"}, headers=mine
        )
        assert again.json() == {"recorded": False}
        assert client.get("/v1/me/learning", headers=mine).json()["observations"] == {"arrive": 1}


def test_the_phone_token_only_reports_places(runtime):
    with TestClient(create_app(runtime, start_channels=False)) as client:
        mine = signed_in(client, "owner@example.com")
        client.patch(
            "/v1/me/learning", json={"on": True, "sources": ["phone"], "pin": PIN}, headers=mine
        )
        assert (
            client.post(
                "/v1/me/learning/phone-token", json={"pin": "9999"}, headers=mine
            ).status_code
            == 403
        )
        made = client.post("/v1/me/learning/phone-token", json={"pin": PIN}, headers=mine).json()
        assert made["url"].endswith("/v1/observations") and made["token"].startswith("ira_t_")
        phone = {"Authorization": f"Bearer {made['token']}"}
        ok = client.post(
            "/v1/observations", json={"event": "leave", "place": "Home"}, headers=phone
        )
        assert ok.json() == {"recorded": True}
        assert client.post("/v1/ask", json={"text": "hi"}, headers=phone).status_code == 403
        assert client.get("/v1/me/learning", headers=phone).status_code == 403
        extra = {"event": "arrive", "place": "Office", "lat": 28.61, "lon": 77.2}
        assert client.post("/v1/observations", json=extra, headers=phone).status_code == 422
        coords = {"event": "arrive", "place": "28.6139, 77.2090"}
        assert client.post("/v1/observations", json=coords, headers=phone).status_code == 400
        listed = client.get("/v1/me/learning", headers=mine).json()["phone_tokens"]
        assert [t["id"] for t in listed] == [made["id"]]
        assert (
            client.delete(f"/v1/me/learning/phone-token/{made['id']}", headers=mine).status_code
            == 200
        )
        gone = client.post(
            "/v1/observations", json={"event": "leave", "place": "Home"}, headers=phone
        )
        assert gone.status_code == 401


async def test_a_mac_observes_only_with_its_routine_skill_and_by_network_hash(store):
    clock = Clock(1_792_000_000.0)
    settings = UserSettings(store)
    hub = DeviceHub(Devices(store))
    told: list = []

    async def notify(user_id, event):
        told.append((user_id, event.title, event.text))

    learning = LearningService(store, settings, notify=notify, clock=clock)
    hub.observer = learning.from_device
    from ira.accounts import Accounts

    user = Accounts(store).create_user("owner@example.com", PASSWORD, "owner")
    _, device = paired(hub.devices, user.id, skills=("chrome",))
    socket, task, _ = await connect(hub, device)

    socket.say({"type": "observe", "kind": "unlock", "network": OFFICE})
    error = await socket.next()
    assert error["type"] == "error" and "routine skill is off" in error["error"]

    hub.devices.set_skills(device.id, ["chrome", "routine"])
    await hub.push_skills(device.id, ["chrome", "routine"])
    assert await socket.next() == {"type": "skills", "skills": ["chrome", "routine"]}
    socket.say({"type": "observe", "kind": "unlock", "network": OFFICE})
    await asyncio.sleep(0.05)
    assert learning.data.observations(user.id) == []  # learning itself is still off

    settings.set(user.id, "learning", True)
    learning.data.add_reminder(user.id, "call the bank", trigger="arrive", place="Office")
    socket.say({"type": "observe", "kind": "unlock", "network": OFFICE, "at": clock.now - 60})
    socket.say({"type": "observe", "kind": "network", "network": "MyHomeWiFi"})
    error = await socket.next()
    assert error["type"] == "error" and "hash only" in error["error"]
    await asyncio.sleep(0.05)
    rows = learning.data.observations(user.id)
    assert [(r["kind"], r["label"], r["at"]) for r in rows] == [("unlock", None, clock.now - 60)]
    assert rows[0]["detail"] == {"network": OFFICE}
    assert told == []  # the network has no name yet

    assert learning.data.name_network(user.id, OFFICE, "Office")
    assert learning.data.observations(user.id)[0]["label"] == "Office"
    socket.say({"type": "observe", "kind": "network", "network": HOME})
    socket.say({"type": "observe", "kind": "wake", "network": OFFICE})
    await asyncio.sleep(0.05)
    assert told == [(user.id, "Reminder: call the bank", "You reached Office.")]
    assert learning.data.reminders(user.id) == []
    await socket.close()
    await task


def test_learning_is_private_and_exported_and_deleted(runtime):
    owner = runtime.accounts.find_user("owner@example.com")
    staff = runtime.accounts.find_user("staff@example.com")
    data: LearningStore = runtime.learning.data
    data.add(owner.id, "arrive", "phone", label="Office")
    data.network_seen(owner.id, None, OFFICE)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        mine = signed_in(client, "owner@example.com")
        theirs = signed_in(client, "staff@example.com")
        assert client.get("/v1/me/learning", headers=theirs).json()["networks"] == []
        assert client.get("/v1/me/observations", headers=theirs).json() == []
        assert (
            client.put(
                f"/v1/me/networks/{OFFICE}", json={"label": "Office"}, headers=theirs
            ).status_code
            == 404
        )
        named = client.put(f"/v1/me/networks/{OFFICE}", json={"label": "Office"}, headers=mine)
        assert named.json()["label"] == "Office"
        export = client.get("/v1/me/export", headers=mine).json()
        assert [o["label"] for o in export["observations"]] == ["Office"]
        assert export["networks"][0]["fingerprint"] == OFFICE
        gone = client.post("/v1/me/data/delete", json={"password": PASSWORD}, headers=mine).json()
        assert gone["observations"] == 1
        assert data.observations(owner.id) == [] and data.networks(owner.id) == []
        assert staff.id != owner.id


def test_old_observations_are_forgotten_after_the_kept_days(store):
    clock = Clock(1_792_000_000.0)
    settings = UserSettings(store)
    learning = LearningService(store, settings, clock=clock)
    from ira.accounts import Accounts

    user = Accounts(store).create_user("owner@example.com", PASSWORD, "owner")
    settings.set(user.id, "learning", True)
    settings.set(user.id, "learning_sources", ["phone"])
    settings.set(user.id, "learning_days", 14)
    learning.data.add(user.id, "arrive", "phone", label="Office", at=clock.now - 20 * 86400)
    asyncio.run(learning.from_phone(user.id, "leave", "Office"))
    kinds: list[Any] = [o["kind"] for o in learning.data.observations(user.id)]
    assert kinds == ["leave"]
