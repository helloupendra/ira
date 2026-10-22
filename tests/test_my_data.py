"""Export my data and Delete my data: one person's own, nobody else's."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.devices.protocol import Event
from ira.models.fake import ScriptedProvider

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret


def signed_in(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/v1/auth/login", json={"email": email, "password": PASSWORD, "use_cookie": False}
    )
    return {"Authorization": f"Bearer {response.json()['session_token']}"}


@pytest.fixture
def runtime(registry):
    runtime = make_runtime(provider=ScriptedProvider(["Hi owner.", "Hi staff."]), registry=registry)
    for email, role in (("owner@example.com", "owner"), ("staff@example.com", "staff")):
        runtime.accounts.create_user(email, PASSWORD, role)
    return runtime


def test_export_has_my_data_only_and_delete_removes_it(runtime):
    owner = runtime.accounts.find_user("owner@example.com")
    staff = runtime.accounts.find_user("staff@example.com")
    devices = runtime.hub.devices
    code, _ = devices.start_pairing(owner.id, "mac", "Office Mac", ["chrome"])
    token, device = devices.redeem(code)
    devices.add_event(owner.id, device.id, Event("watch_done", "Upload finished", "100%", {}))
    runtime.assistant.user_settings.set(owner.id, "assistant_name", "Tara")
    with TestClient(create_app(runtime, start_channels=False)) as client:
        mine = signed_in(client, "owner@example.com")
        theirs = signed_in(client, "staff@example.com")
        client.post("/v1/ask", json={"text": "hello", "conversation_id": "c1"}, headers=mine)
        client.post(
            "/v1/ask", json={"text": "staff question", "conversation_id": "c9"}, headers=theirs
        )

        response = client.get("/v1/me/export", headers=mine)
        assert response.status_code == 200
        assert response.headers["content-disposition"].startswith(
            'attachment; filename="ira-my-data-'
        )
        data = response.json()
        assert data["user"]["email"] == "owner@example.com"
        assert data["settings"] == {"assistant_name": "Tara"}
        texts = [m["content"] for c in data["conversations"] for m in c["messages"]]
        assert "hello" in texts and "staff question" not in texts
        assert data["devices"][0]["label"] == "Office Mac"
        assert data["events"][0]["title"] == "Upload finished"
        assert token not in response.text and "token_hash" not in response.text
        assert "password" not in response.text and "pin_hash" not in response.text

        not_mine = PASSWORD + "-wrong"
        wrong = client.post("/v1/me/data/delete", json={"password": not_mine}, headers=mine)
        assert wrong.status_code == 403
        deleted = client.post("/v1/me/data/delete", json={"password": PASSWORD}, headers=mine)
        assert deleted.status_code == 200
        assert deleted.json() == {
            "conversations": 1,
            "messages": 2,
            "devices": 1,
            "events": 1,
            "activity": 0,
            "settings": 1,
            "observations": 0,
            "learnings": 0,
            "reminders": 0,
        }
        after = client.get("/v1/me/export", headers=mine).json()
        assert after["conversations"] == [] and after["devices"] == [] and after["events"] == []
        assert devices.by_token(token) is None
        # The other person's data is untouched, and the account itself stays.
        staff_data = client.get("/v1/me/export", headers=theirs).json()
        assert [m["content"] for m in staff_data["conversations"][0]["messages"]][
            0
        ] == "staff question"
        assert runtime.accounts.get_user(owner.id) is not None
        log = client.get("/v1/admin/changes", headers=mine).json()
        assert log[0]["what"] == "me.data_deleted" and json.dumps(log[0]["after"])
        assert staff.id != owner.id


def test_export_and_delete_need_a_session(runtime):
    owner = runtime.accounts.find_user("owner@example.com")
    api_token, _ = runtime.accounts.create_token(owner, "phone", ["ask"])
    with TestClient(create_app(runtime, start_channels=False)) as client:
        headers = {"Authorization": f"Bearer {api_token}"}
        assert client.get("/v1/me/export", headers=headers).status_code == 403
        delete = client.post("/v1/me/data/delete", json={"password": PASSWORD}, headers=headers)
        assert delete.status_code == 403
