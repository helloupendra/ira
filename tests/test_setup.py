"""First-run setup: a one-time code printed at start-up guards the owner account."""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from ira import setupcode
from ira.accounts import AccountError, Accounts
from ira.channels.http import create_app
from ira.cli import main, setup_banner
from ira.store import Store
from ira.web import setup_page

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


def test_a_restart_keeps_the_link_already_handed_out(tmp_path):
    path = tmp_path / "ira.db"
    first = make_runtime(store=Store(path))
    with TestClient(create_app(first, start_channels=False)):
        handed_out = first.setup_code
    assert handed_out
    # The server restarts: a new process, the same database.
    second = make_runtime(store=Store(path))
    with TestClient(create_app(second, start_channels=False)) as client:
        assert second.setup_code == handed_out
        assert client.post("/v1/setup/owner", json=owner_body(handed_out)).status_code == 200
        again = client.post("/v1/setup/owner", json=owner_body(handed_out, "b@example.com"))
        assert again.status_code == 409
    assert second.setup_code is None
    assert Store(path).get_setting(setupcode.KEY) is None


def test_the_code_expires_after_a_day_and_a_new_one_is_logged(tmp_path, caplog):
    store = Store(tmp_path / "ira.db")
    old = setupcode.renew(store, clock=lambda: time.time() - setupcode.TTL_SECONDS - 1)
    assert setupcode.current(store) is None
    runtime = make_runtime(store=store)
    runtime.setup_code_shown = True
    fresh = runtime.ensure_setup_code()
    assert fresh and fresh != old
    assert f"#code={fresh}" in caplog.text
    assert runtime.ensure_setup_code() == fresh


def test_ira_setup_new_code_replaces_the_link(tmp_path, capsys):
    config = tmp_path / "ira.yaml"
    config.write_text(
        "data_dir: ./data\nchannels:\n  http:\n    public_url: https://ira.example.com\n",
        encoding="utf-8",
    )
    store = Store(tmp_path / "data" / "ira.db")
    old = setupcode.renew(store)
    assert main(["--config", str(config), "setup", "--new-code"]) == 0
    new = setupcode.current(store)
    assert new and new != old
    printed = capsys.readouterr().out
    assert f"https://ira.example.com{setup_page()}#code={new}" in printed
    assert "The earlier link no longer works." in printed
    Accounts(store).create_first_owner("owner@example.com", PASSWORD)
    assert main(["--config", str(config), "setup", "--new-code"]) == 1
