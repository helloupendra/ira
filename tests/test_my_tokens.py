"""Tokens for Siri: anyone may make one with their PIN, and it can only ask."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.models.fake import ScriptedProvider

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
PIN = "4321"


def login(client, email):
    body = {"email": email, "password": PASSWORD, "use_cookie": False}
    token = client.post("/v1/auth/login", json=body).json()["session_token"]
    return {"Authorization": f"Bearer {token}"}


def test_a_siri_token_is_made_with_the_pin_and_only_asks():
    runtime = make_runtime(provider=ScriptedProvider(["Your next booking is at 10."]))
    runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    staff = runtime.accounts.create_user("staff@example.com", PASSWORD, "staff")
    with TestClient(create_app(runtime, start_channels=False)) as client:
        mine = login(client, "staff@example.com")
        assert client.post("/v1/me/tokens", json={"pin": PIN}, headers=mine).status_code == 409
        runtime.guard.set_pin(PIN, user_id=staff.id)
        assert client.post("/v1/me/tokens", json={"pin": "0000"}, headers=mine).status_code == 403
        made = client.post("/v1/me/tokens", json={"pin": PIN}, headers=mine).json()
        assert made["label"] == "Siri on iPhone" and made["scopes"] == ["ask"]
        siri = {"Authorization": f"Bearer {made['token']}"}

        # It asks, as its person, and nothing more.
        answer = client.post("/v1/ask", json={"text": "my next booking?"}, headers=siri)
        assert answer.json()["text"] == "Your next booking is at 10."
        assert client.get("/v1/me/tokens", headers=siri).status_code in (401, 403)
        assert client.post("/v1/me/tokens", json={"pin": PIN}, headers=siri).status_code in (
            401,
            403,
        )
        assert client.post("/v1/actions/act_x/confirm", json={}, headers=siri).status_code == 403
        assert client.get("/v1/admin/overview", headers=siri).status_code == 403

        listed = client.get("/v1/me/tokens", headers=mine).json()
        assert [(t["id"], t["scopes"]) for t in listed] == [(made["id"], ["ask"])]
        assert made["token"] not in str(listed)
        owner = login(client, "owner@example.com")
        path = f"/v1/me/tokens/{made['id']}"
        assert client.delete(path, headers=owner).status_code == 404  # not the owner's
        assert client.delete(path, headers=mine).json() == {"ok": True}
        assert client.post("/v1/ask", json={"text": "hi"}, headers=siri).status_code == 401
        assert client.get("/v1/me/tokens", headers=mine).json() == []
