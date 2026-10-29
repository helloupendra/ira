"""Drop: a person's own inbox, encrypted at rest, shared live by their devices."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.devices.hub import Connection
from ira.drop import CHUNK, Drop, DropError, kind_of
from ira.store import Store

from .conftest import Clock, make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret


def drop_in(tmp_path: Path, **kwargs) -> tuple[Drop, Clock]:
    clock = Clock()
    key = os.urandom(32)
    return Drop(Store(":memory:"), tmp_path / "drop", lambda: key, clock=clock, **kwargs), clock


def test_text_and_links():
    assert kind_of("https://example.com/a?b=1") == "link"
    assert kind_of(" http://example.com ") == "link"
    assert kind_of("see https://example.com") == "text"


def test_a_file_is_stored_encrypted_and_any_tampering_is_caught(tmp_path):
    drop, _ = drop_in(tmp_path)
    data = os.urandom(CHUNK * 2 + 12345)  # three chunks
    item = drop.add_file(1, io.BytesIO(data), "../../plan.pdf", None, from_label="Mac")
    assert (item.kind, item.name, item.mime, item.size) == (
        "file",
        "plan.pdf",
        "application/pdf",
        len(data),
    )
    assert item.sha256 == hashlib.sha256(data).hexdigest()
    stored = (tmp_path / "drop" / "1" / f"{item.id}.bin").read_bytes()
    assert (
        data[:64] not in stored
        and oct(os.stat(tmp_path / "drop" / "1" / f"{item.id}.bin").st_mode)[-3:] == "600"
    )
    assert b"".join(drop.read(item)) == data

    path = tmp_path / "drop" / "1" / f"{item.id}.bin"
    flipped = bytearray(stored)
    flipped[100] ^= 1
    path.write_bytes(bytes(flipped))
    with pytest.raises(DropError, match="integrity"):
        b"".join(drop.read(item))
    path.write_bytes(stored[: len(stored) // 2])  # cut short
    with pytest.raises(DropError):
        b"".join(drop.read(item))

    # A chunk cannot move to another item: each is bound to its item and place.
    other = drop.add_file(1, io.BytesIO(data), "copy.pdf", None, from_label="Mac")
    path.write_bytes((tmp_path / "drop" / "1" / f"{other.id}.bin").read_bytes())
    with pytest.raises(DropError, match="integrity"):
        b"".join(drop.read(item))

    empty = drop.add_file(1, io.BytesIO(b""), "empty.txt", "text/plain", from_label="Web")
    assert empty.size == 0 and b"".join(drop.read(empty)) == b""


def test_limits_quota_and_expiry(tmp_path):
    drop, clock = drop_in(tmp_path, max_file_bytes=CHUNK, quota_bytes=CHUNK + 10, max_text=50)
    with pytest.raises(DropError) as too_big:
        drop.add_file(1, io.BytesIO(b"x" * (CHUNK + 1)), "big.bin", None, from_label="Web")
    assert too_big.value.status == 413
    assert drop.list(1) == [] and not list((tmp_path / "drop" / "1").iterdir())  # nothing left
    drop.add_file(1, io.BytesIO(b"x" * CHUNK), "one.bin", None, from_label="Web")
    with pytest.raises(DropError) as full:
        drop.add_file(1, io.BytesIO(b"y" * 20), "two.bin", None, from_label="Web")
    assert full.value.status == 507
    with pytest.raises(DropError) as long:
        drop.add_text(1, "z" * 51, from_label="Web")
    assert long.value.status == 413
    drop.add_text(2, "someone else's", from_label="Web")
    clock.advance(30 * 86400 + 1)
    assert drop.list(1) == [] and drop.clean() == 2
    assert not list((tmp_path / "drop" / "1").iterdir())


class Socket:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def send_text(self, data: str) -> None:
        self.frames.append(json.loads(data))

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        pass


def test_the_inbox_over_http_and_live_to_the_other_devices(tmp_path):
    runtime = make_runtime(data_dir=tmp_path)
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    runtime.accounts.create_user("staff@example.com", PASSWORD, "staff")
    devices = runtime.hub.devices
    sockets = {}
    tokens = {}
    for name, kind in (("Pixel 7", "android"), ("Mac", "mac")):
        code, _ = devices.start_pairing(owner.id, kind, name, [])
        token, device = devices.redeem(code)
        tokens[name] = {"Authorization": f"Bearer {token}"}
        sockets[name] = Socket()
        runtime.hub.connections[device.id] = Connection(device, sockets[name], {}, 0.0)

    def login(client, email):
        body = {"email": email, "password": PASSWORD, "use_cookie": False}
        return {
            "Authorization": "Bearer "
            + client.post("/v1/auth/login", json=body).json()["session_token"]
        }

    with TestClient(create_app(runtime, start_channels=False)) as client:
        me, them = login(client, "owner@example.com"), login(client, "staff@example.com")
        made = client.post("/v1/me/drop", json={"text": "https://example.com/plan"}, headers=me)
        assert made.status_code == 201
        link = made.json()
        assert (link["kind"], link["from_label"], link["from_device_id"]) == ("link", "Web", None)
        # Every device heard of it at once.
        assert sockets["Mac"].frames[-1] == {"type": "drop", "event": "new", "item": link}

        data = os.urandom(5000)
        sent = client.post(
            "/v1/me/drop",
            files={"file": ("photo.jpg", data, "image/jpeg")},
            data={"text": "from the phone"},
            headers=tokens["Pixel 7"],
        ).json()
        assert (sent["name"], sent["mime"], sent["size"], sent["text"]) == (
            "photo.jpg", "image/jpeg", 5000, "from the phone",
        )  # fmt: skip
        assert sent["from_label"] == "Pixel 7"
        assert sockets["Mac"].frames[-1]["item"]["id"] == sent["id"]
        assert all(
            f["item"]["id"] != sent["id"] for f in sockets["Pixel 7"].frames
        )  # not back to itself

        listed = client.get("/v1/me/drop?limit=1", headers=tokens["Mac"]).json()
        assert [i["id"] for i in listed["items"]] == [sent["id"]] and listed["has_more"]
        newer = client.get(f"/v1/me/drop?after_id={link['id']}", headers=me).json()
        assert [i["id"] for i in newer["items"]] == [sent["id"]]

        got = client.get(f"/v1/me/drop/{sent['id']}/file", headers=tokens["Mac"])
        assert got.content == data and got.headers["content-type"] == "image/jpeg"
        assert "attachment" in got.headers["content-disposition"]
        assert got.headers["x-content-type-options"] == "nosniff"

        # Someone else's items do not exist for them.
        assert client.get("/v1/me/drop", headers=them).json()["items"] == []
        assert client.get(f"/v1/me/drop/{sent['id']}/file", headers=them).status_code == 404
        assert client.delete(f"/v1/me/drop/{sent['id']}", headers=them).status_code == 404
        assert client.post("/v1/me/drop", json={"nope": 1}, headers=me).status_code == 400

        assert client.delete(f"/v1/me/drop/{sent['id']}", headers=me).status_code == 204
        assert sockets["Pixel 7"].frames[-1] == {
            "type": "drop",
            "event": "deleted",
            "id": sent["id"],
        }
        assert client.get(f"/v1/me/drop/{sent['id']}/file", headers=me).status_code == 404

        exported = client.get("/v1/me/export", headers=me).json()
        assert [i["id"] for i in exported["drop"]] == [link["id"]]
        client.post("/v1/me/drop", files={"file": ("a.txt", b"secret", "text/plain")}, headers=me)
        gone = client.post("/v1/me/data/delete", json={"password": PASSWORD}, headers=me)
        assert gone.status_code == 200
    assert runtime.drop.list(owner.id) == []
    assert not (tmp_path / "drop" / str(owner.id)).exists()


def test_a_key_that_may_only_ask_cannot_read_the_inbox(tmp_path):
    runtime = make_runtime(data_dir=tmp_path)
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    runtime.accounts.create_user("viewer@example.com", PASSWORD, "viewer")
    runtime.guard.set_pin("4321", user_id=owner.id)
    runtime.drop.add_text(owner.id, "the plan", from_label="Mac")
    with TestClient(create_app(runtime, start_channels=False)) as client:

        def login(email):
            body = {"email": email, "password": PASSWORD, "use_cookie": False}
            token = client.post("/v1/auth/login", json=body).json()["session_token"]
            return {"Authorization": f"Bearer {token}"}

        me = login("owner@example.com")

        def key(**extra):
            made = client.post("/v1/me/tokens", json={"pin": "4321", **extra}, headers=me).json()
            return made["scopes"], {"Authorization": f"Bearer {made['token']}"}

        scopes, siri = key()
        assert scopes == ["ask"]
        assert client.get("/v1/me/drop", headers=siri).status_code == 403
        assert client.post("/v1/me/drop", json={"text": "x"}, headers=siri).status_code == 403
        scopes, cli = key(label="ira CLI", drop=True)
        assert scopes == ["ask", "drop"]
        assert [i["text"] for i in client.get("/v1/me/drop", headers=cli).json()["items"]] == [
            "the plan"
        ]
        assert client.get("/v1/me/drop", headers=login("viewer@example.com")).status_code == 403
