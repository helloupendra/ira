"""Changing a password or an email: your own, an owner's reset, and from the command line."""

from __future__ import annotations

import io
import json
import sys

import pytest
from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.cli import main

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
NEW = "a-new-horse-battery"  # pragma: allowlist secret


@pytest.fixture
def runtime(registry):
    runtime = make_runtime(registry=registry)
    runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    runtime.accounts.create_user("admin@example.com", PASSWORD, "admin")
    runtime.accounts.create_user("staff@example.com", PASSWORD, "staff")
    return runtime


@pytest.fixture
def client(runtime):
    with TestClient(create_app(runtime, start_channels=False)) as test_client:
        yield test_client


def login(client, email, password=PASSWORD):
    body = {"email": email, "password": password, "use_cookie": False}
    response = client.post("/v1/auth/login", json=body)
    if response.status_code != 200:
        return None
    return {"Authorization": f"Bearer {response.json()['session_token']}"}


def signed_in(client, headers) -> bool:
    return client.get("/v1/auth/me", headers=headers).status_code == 200


def changes(client, headers) -> list[dict]:
    return client.get("/v1/admin/changes", headers=headers).json()


def test_changing_your_password_signs_out_your_other_sessions(client, runtime):
    here, there = login(client, "staff@example.com"), login(client, "staff@example.com")
    token, _ = runtime.accounts.create_token(
        runtime.accounts.find_user("staff@example.com"), "script", ["ask"]
    )
    wrong = {"current_password": "not-my-password", "new_password": NEW}  # pragma: allowlist secret
    assert client.put("/v1/me/password", json=wrong, headers=here).status_code == 403
    short = {"current_password": PASSWORD, "new_password": "short"}  # pragma: allowlist secret
    assert client.put("/v1/me/password", json=short, headers=here).status_code == 400
    body = {"current_password": PASSWORD, "new_password": NEW}
    assert client.put("/v1/me/password", json=body, headers=here).json() == {"ended": 1}
    assert signed_in(client, here) and not signed_in(client, there)
    assert signed_in(client, {"Authorization": f"Bearer {token}"})  # tokens are separate keys
    assert login(client, "staff@example.com") is None
    assert login(client, "staff@example.com", NEW)
    # An API token cannot change a password.
    tokened = client.put("/v1/me/password", json=body, headers={"Authorization": f"Bearer {token}"})
    assert tokened.status_code == 403
    log = changes(client, login(client, "owner@example.com"))
    row = next(r for r in log if r["what"] == "account.password")
    assert row["target"] == "staff@example.com" and NEW not in json.dumps(log)


def test_an_owner_resets_a_password_and_every_session_of_theirs_ends(client):
    owner, staff = login(client, "owner@example.com"), login(client, "staff@example.com")
    admin = login(client, "admin@example.com")
    staff_id = client.get("/v1/auth/me", headers=staff).json()["user"]["id"]
    reset = {"new_password": NEW}
    assert (
        client.put(f"/v1/admin/users/{staff_id}/password", json=reset, headers=admin).status_code
        == 403
    )
    assert client.put("/v1/admin/users/999/password", json=reset, headers=owner).status_code == 404
    done = client.put(f"/v1/admin/users/{staff_id}/password", json=reset, headers=owner)
    assert done.json() == {"ended": 1}
    assert not signed_in(client, staff)
    assert login(client, "staff@example.com", NEW)
    assert changes(client, owner)[0]["what"] == "user.password_reset"


def test_emails_change_with_your_password_or_by_an_owner(client):
    admin = login(client, "admin@example.com")
    move = {"email": "Desk@Example.com", "password": PASSWORD}
    bad = {**move, "password": "nope"}  # pragma: allowlist secret
    assert client.put("/v1/me/email", json=bad, headers=admin).status_code == 403
    taken = {**move, "email": "staff@example.com"}
    assert client.put("/v1/me/email", json=taken, headers=admin).status_code == 400
    assert client.put("/v1/me/email", json=move, headers=admin).status_code == 200
    assert login(client, "desk@example.com") and login(client, "admin@example.com") is None

    owner = login(client, "owner@example.com")
    staff_id = client.get("/v1/auth/me", headers=login(client, "staff@example.com")).json()["user"][
        "id"
    ]
    them = {"email": "front@example.com"}
    assert (
        client.put(f"/v1/admin/users/{staff_id}/email", json=them, headers=admin).status_code == 403
    )
    row = client.put(f"/v1/admin/users/{staff_id}/email", json=them, headers=owner).json()
    assert row["email"] == "front@example.com"
    log = changes(client, owner)
    assert (log[0]["what"], log[0]["before"], log[0]["after"]) == (
        "user.email",
        "staff@example.com",
        "front@example.com",
    )
    assert any(r["what"] == "account.email" and r["before"] == "admin@example.com" for r in log)


def test_the_command_line_sets_a_password_and_an_email(tmp_path, capsys):
    config = tmp_path / "ira.yaml"
    config.write_text("data_dir: ./data\n", encoding="utf-8")

    def run(*args, stdin=""):
        original, sys.stdin = sys.stdin, io.StringIO(stdin)
        try:
            return main(["--config", str(config), *args])
        finally:
            sys.stdin = original

    assert run("setup", "--email", "owner@example.com", stdin=PASSWORD + "\n") == 0
    assert run("user", "password", "nobody@example.com", stdin=NEW + "\n") == 1
    assert run("user", "password", "owner@example.com", stdin="short\n") == 1
    assert run("user", "password", "owner@example.com", stdin=NEW + "\n") == 0
    assert "Changed the password of owner@example.com" in capsys.readouterr().out
    assert run("user", "email", "owner@example.com", "me@example.com") == 0
    assert "owner@example.com now signs in as me@example.com." in capsys.readouterr().out

    from ira.accounts import Accounts
    from ira.store import Store

    accounts = Accounts(Store(tmp_path / "data" / "ira.db"))
    assert accounts.authenticate("me@example.com", NEW) is not None
    assert accounts.authenticate("me@example.com", PASSWORD) is None
