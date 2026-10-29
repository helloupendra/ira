"""A paired device's token over HTTP: it asks and talks for its person, and does nothing more."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ira.channels.http import create_app

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret


def pair(runtime, user_id: int) -> tuple[str, int]:
    devices = runtime.hub.devices
    code, _ = devices.start_pairing(user_id, "mac", "Office Mac", ["files"])
    token, device = devices.redeem(code)
    return token, device.id


def test_a_device_token_asks_and_talks_for_its_person_only(registry):
    runtime = make_runtime(registry=registry)
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    token, device_id = pair(runtime, owner.id)
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app(runtime, start_channels=False)) as client:
        info = client.get("/v1/info", headers=headers).json()
        assert info["user"]["email"] == "owner@example.com"
        assert sorted(info["permissions"]) == ["actions", "ask", "drop", "voice"]
        asked = client.post(
            "/v1/ask", json={"text": "hello", "conversation_id": "m1"}, headers=headers
        )
        assert asked.status_code == 200
        streamed = client.post("/v1/ask/stream", json={"text": "hello"}, headers=headers)
        assert streamed.status_code == 200 and "data:" in streamed.text
        # Nothing an admin does, and nothing that needs a signed-in session.
        assert client.get("/v1/admin/overview", headers=headers).status_code == 403
        assert client.get("/v1/me/settings", headers=headers).status_code == 200  # reading: ask
        changed = client.patch("/v1/me/settings", json={"assistant_name": "X"}, headers=headers)
        assert changed.status_code == 403
        assert client.get("/v1/me/sessions", headers=headers).status_code == 403
        # Revoked: it works nowhere at once.
        runtime.hub.devices.revoke(device_id)
        assert client.get("/v1/info", headers=headers).status_code == 401


def test_a_device_cannot_do_more_than_its_persons_role(registry):
    runtime = make_runtime(registry=registry)
    runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    viewer = runtime.accounts.create_user("viewer@example.com", PASSWORD, "viewer")
    token, _ = pair(runtime, viewer.id)
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app(runtime, start_channels=False)) as client:
        assert client.get("/v1/info", headers=headers).json()["permissions"] == []
        assert client.post("/v1/ask", json={"text": "hi"}, headers=headers).status_code == 403
