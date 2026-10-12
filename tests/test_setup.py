"""First-run setup: a one-time code printed at start-up guards the owner account."""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from ira.accounts import AccountError, Accounts
from ira.channels.http import create_app
from ira.cli import setup_banner
from ira.store import Store

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret


@pytest.fixture
def runtime():
    return make_runtime()


@pytest.fixture
def client(runtime):
    with TestClient(create_app(runtime, start_channels=False)) as test_client:
        yield test_client


def owner_body(code: str, email: str = "owner@example.com") -> dict:
    return {"code": code, "email": email, "password": PASSWORD}


def test_status_reports_whether_an_owner_is_needed(client, runtime):
    assert client.get("/v1/setup/status").json()["needs_owner"] is True
    runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    assert client.get("/v1/setup/status").json()["needs_owner"] is False


def test_the_owner_needs_the_code(client, runtime):
    assert runtime.setup_code  # made at start-up, because no user exists
    assert client.post("/v1/setup/owner", json=owner_body("")).status_code == 403
    assert client.post("/v1/setup/owner", json=owner_body("0000-0000-0000")).status_code == 403
    missing = {"email": "owner@example.com", "password": PASSWORD}
    assert client.post("/v1/setup/owner", json=missing).status_code == 422
    assert runtime.accounts.needs_owner()


def test_the_code_works_once_and_signs_the_owner_in(client, runtime):
    code = runtime.setup_code
    created = client.post("/v1/setup/owner", json=owner_body(code.lower()))
    assert created.status_code == 200
    assert created.json()["user"]["role"] == "owner"
    cookie = created.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/v1/auth/me").json()["user"]["email"] == "owner@example.com"

    # The code is dead: the same code, or the old endpoint, cannot make a second owner.
    assert runtime.setup_code is None
    again = client.post("/v1/setup/owner", json=owner_body(code, "second@example.com"))
    assert again.status_code == 409
    legacy = {"email": "second@example.com", "password": PASSWORD, "setup_code": code}
    assert client.post("/v1/auth/setup", json=legacy).status_code == 409
    assert [u.email for u in runtime.accounts.users()] == ["owner@example.com"]
    changes = client.get("/v1/admin/changes").json()
    assert changes[0]["what"] == "setup.owner"


def test_a_weak_password_keeps_the_code_alive(client, runtime):
    code = runtime.setup_code
    weak = client.post("/v1/setup/owner", json={**owner_body(code), "password": "short"})
    assert weak.status_code == 400
    assert runtime.setup_code == code
    assert client.post("/v1/setup/owner", json=owner_body(code)).status_code == 200


def test_wrong_codes_are_throttled(client, runtime):
    for _ in range(5):
        assert client.post("/v1/setup/owner", json=owner_body("WRONG")).status_code == 403
    assert client.post("/v1/setup/owner", json=owner_body(runtime.setup_code)).status_code == 429


def test_only_one_of_two_racing_setups_wins(tmp_path):
    # Two connections to one file, as two processes would have.
    path = tmp_path / "ira.db"
    first, second = Accounts(Store(path)), Accounts(Store(path))
    results: list[str] = []
    barrier = threading.Barrier(2)

    def claim(accounts: Accounts, email: str) -> None:
        barrier.wait()
        try:
            accounts.create_first_owner(email, PASSWORD)
            results.append("created")
        except AccountError:
            results.append("refused")

    threads = [
        threading.Thread(target=claim, args=(first, "a@example.com")),
        threading.Thread(target=claim, args=(second, "b@example.com")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["created", "refused"]
    assert first.count() == 1


def test_serve_prints_the_setup_link_with_the_code(tmp_path, monkeypatch):
    from ira import web

    monkeypatch.setattr(web, "ADMIN_DIR", tmp_path)  # no console built: the chat's form
    banner = setup_banner("7F3A-91C2-0B4E", "0.0.0.0", 8765)
    assert "http://127.0.0.1:8765/#code=7F3A-91C2-0B4E" in banner
    assert "works once" in banner

    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    banner = setup_banner("7F3A-91C2-0B4E", "192.0.2.10", 9000)
    assert "http://192.0.2.10:9000/admin/setup#code=7F3A-91C2-0B4E" in banner
