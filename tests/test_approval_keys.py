"""Approving with a device's key (a fingerprint) instead of the PIN."""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from ira.approval_keys import message
from ira.channels.http import create_app
from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
PIN = "4321"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def public(key: ec.EllipticCurvePrivateKey) -> str:
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(der).decode()


def sign(key: ec.EllipticCurvePrivateKey, action: dict) -> str:
    """As a device does: from the action it was given, never the server's own record."""
    data = message(action["id"], action["summary"], action["expires_at"])
    return b64(key.sign(data, ec.ECDSA(hashes.SHA256())))


def refund() -> ChatResponse:
    return ChatResponse(
        text="", tool_calls=[ToolCall("c1", "refund", '{"order_id": "A1", "amount": 5}')]
    )


def test_a_fingerprint_on_the_device_confirms_instead_of_the_pin(registry, ledger):
    provider = ScriptedProvider([refund(), "PIN?", "Done.", refund(), "PIN?", "ok"])
    runtime = make_runtime(provider=provider, registry=registry)
    owner = runtime.accounts.create_user("owner@example.com", PASSWORD, "owner")
    runtime.guard.set_pin(PIN, user_id=owner.id, actor=owner.email, channel="test")
    devices = runtime.hub.devices
    code, _ = devices.start_pairing(owner.id, "android", "Pixel 7", [])
    token, phone = devices.redeem(code)
    code, _ = devices.start_pairing(owner.id, "mac", "Mac", [])
    other_token, mac = devices.redeem(code)
    key, stranger = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    with TestClient(create_app(runtime, start_channels=False)) as client:
        body = {"email": "owner@example.com", "password": PASSWORD, "use_cookie": False}
        session = client.post("/v1/auth/login", json=body).json()["session_token"]
        me = {"Authorization": f"Bearer {session}"}
        device = {"Authorization": f"Bearer {token}"}

        enrol = {"public_key": public(key), "algorithm": "ES256", "pin": PIN}
        assert client.post("/v1/me/approval-keys", json=enrol, headers=me).status_code == 403
        wrong_pin = {**enrol, "pin": "0000"}
        assert (
            client.post("/v1/me/approval-keys", json=wrong_pin, headers=device).status_code == 403
        )
        p384 = {**enrol, "public_key": public(ec.generate_private_key(ec.SECP384R1()))}
        assert client.post("/v1/me/approval-keys", json=p384, headers=device).status_code == 422
        made = client.post("/v1/me/approval-keys", json=enrol, headers=device).json()
        assert (made["device_id"], made["device"]) == (phone.id, "Pixel 7 (Android)")
        assert [k["device_id"] for k in client.get("/v1/me/approval-keys", headers=me).json()] == [
            phone.id
        ]

        action = client.post("/v1/ask", json={"text": "refund A1"}, headers=me).json()["action"]
        pending = action  # what the device received, with expires_at in whole seconds
        assert action["expires_at"] == int(runtime.guard.get(action["id"]).expires_at)
        path = f"/v1/actions/{action['id']}/confirm"
        neither = client.post(path, json={}, headers=device)
        assert neither.status_code == 422
        bad = client.post(
            path, json={"device_id": phone.id, "signature": sign(stranger, pending)}, headers=device
        )
        assert bad.status_code == 403 and bad.json()["status"] == "wrong_pin"
        assert bad.json()["attempts_left"] == 2  # counted like a wrong PIN
        as_mac = {"device_id": mac.id, "signature": sign(key, pending)}  # the Mac has no key
        assert client.post(path, json=as_mac, headers=device).json()["status"] == "wrong_pin"
        good = {"device_id": phone.id, "signature": sign(key, pending)}
        done = client.post(path, json=good, headers=device).json()
        assert done["status"] == "executed" and ledger.refunds == [("A1", 5)]

        # A signature is for one action only, and a removed key signs nothing.
        second = client.post("/v1/ask", json={"text": "refund A1 again"}, headers=me).json()
        later = second["action"]
        replay = {"device_id": phone.id, "signature": good["signature"]}
        assert client.post(
            f"/v1/actions/{later['id']}/confirm", json=replay, headers=device
        ).json()["status"] in ("wrong_pin", "locked")
        assert client.delete(f"/v1/me/approval-keys/{phone.id}", headers=me).json() == {"ok": True}
        assert client.get("/v1/me/approval-keys", headers=me).json() == []
    assert ledger.refunds == [("A1", 5)]
    del other_token
