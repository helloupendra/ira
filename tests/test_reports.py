"""Reporting an answer: only your own, from the web or a paired device, and the console's list."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.models.fake import ScriptedProvider

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret


def login(client, email):
    body = {"email": email, "password": PASSWORD, "use_cookie": False}
    token = client.post("/v1/auth/login", json=body).json()["session_token"]
    return {"Authorization": f"Bearer {token}"}


def test_people_report_their_own_answers_and_admins_read_them():
    runtime = make_runtime(provider=ScriptedProvider(["Take two of these pills."]))
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    runtime.accounts.create_user("staff@example.com", PASSWORD, "staff")
    devices = runtime.hub.devices
    code, _ = devices.start_pairing(owner.id, "android", "Pixel 7", [])
    phone = {"Authorization": f"Bearer {devices.redeem(code)[0]}"}
    with TestClient(create_app(runtime, start_channels=False)) as client:
        mine, theirs = login(client, "owner@example.com"), login(client, "staff@example.com")
        answer = client.post("/v1/ask", json={"text": "headache?"}, headers=mine).json()
        report = {
            "message_id": answer["message_id"],
            "reason": "harmful",
            "note": " medical  advice ",
        }
        assert client.post("/v1/me/reports", json=report, headers=theirs).status_code == 404
        assert (
            client.post(
                "/v1/me/reports", json={**report, "reason": "meh"}, headers=mine
            ).status_code
            == 422
        )
        made = client.post("/v1/me/reports", json=report, headers=mine).json()
        assert made["id"].startswith("rep_") and made["status"] == "open"
        # From the phone too, with its device token.
        again = {"message_id": answer["message_id"], "reason": "wrong"}
        assert client.post("/v1/me/reports", json=again, headers=phone).status_code == 200
        assert client.get("/v1/admin/reports", headers=theirs).status_code == 403
        rows = client.get("/v1/admin/reports", headers=mine).json()
        assert [r["reason"] for r in rows] == ["wrong", "harmful"]
        first = rows[1]
        assert first["email"] == "owner@example.com" and first["note"] == "medical advice"
        assert first["answer"] == "Take two of these pills." and first["status"] == "open"
        path = f"/v1/admin/reports/{first['id']}/close"
        assert client.post(path, headers=phone).status_code == 403  # a device cannot manage
        assert client.post(path, headers=mine).json() == {"ok": True}
        assert client.post(path, headers=mine).status_code == 404
        still_open = client.get("/v1/admin/reports?status=open", headers=mine).json()
        assert [r["reason"] for r in still_open] == ["wrong"]
        gone = client.post("/v1/me/data/delete", json={"password": PASSWORD}, headers=mine)
        assert gone.status_code == 200
    assert runtime.store.one("SELECT COUNT(*) AS n FROM reports")["n"] == 0
