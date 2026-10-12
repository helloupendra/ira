"""The admin console's write API: who may change what, and what gets recorded."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.models.fake import ScriptedProvider
from ira.voice.providers import FakeTTS

from .conftest import FAST_PIN_ITERATIONS, make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
WRONG_PASSWORD = "not-my-password"  # pragma: allowlist secret


class People:
    """One account per role, each with a bearer session token."""

    def __init__(self, runtime) -> None:
        accounts = runtime.accounts
        self.runtime = runtime
        self.owner = accounts.create_first_owner("owner@example.com", PASSWORD)
        self.admin = accounts.create_user("manager@example.com", PASSWORD, "admin")
        self.staff = accounts.create_user("desk@example.com", PASSWORD, "staff")
        self.viewer = accounts.create_user("books@example.com", PASSWORD, "viewer")

    def session(self, user) -> dict[str, str]:
        token, _ = self.runtime.accounts.start_session(user)
        return {"Authorization": f"Bearer {token}"}

    def token(self, user, scopes: list[str]) -> dict[str, str]:
        token, _ = self.runtime.accounts.create_token(user, "test", scopes)
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def runtime(registry):
    rt = make_runtime(provider=ScriptedProvider(["ready"] * 10), registry=registry, tts=FakeTTS())
    rt.guard.pin_iterations = FAST_PIN_ITERATIONS
    return rt


@pytest.fixture
def people(runtime) -> People:
    return People(runtime)


@pytest.fixture
def client(runtime):
    with TestClient(create_app(runtime, start_channels=False)) as test_client:
        yield test_client


def changes(client, people) -> list[dict]:
    return client.get("/v1/admin/changes", headers=people.session(people.owner)).json()


# The denials the console relies on the server for.


WRITES = [
    ("post", "/v1/admin/users/invites", {"email": "new@example.com", "role": "staff"}),
    ("patch", "/v1/admin/users/1", {"role": "admin"}),
    ("delete", "/v1/admin/users/3", None),
    ("post", "/v1/admin/users/3/reset-pin", None),
    ("post", "/v1/admin/tokens", {"label": "x", "scopes": ["ask"]}),
    ("delete", "/v1/admin/tokens/tok_x", None),
]


def call(client, method: str, path: str, body, headers):
    kwargs = {"headers": headers}
    if body is not None:
        kwargs["json"] = body
    return client.request(method.upper(), path, **kwargs)


def test_a_viewer_and_staff_cannot_write_anything(client, people):
    for user in (people.viewer, people.staff):
        headers = people.session(user)
        for method, path, body in WRITES:
            response = call(client, method, path, body, headers)
            assert response.status_code == 403, (user.role, path, response.status_code)


def test_an_admin_cannot_manage_users(client, people):
    headers = people.session(people.admin)
    for method, path, body in WRITES[:4]:
        response = call(client, method, path, body, headers)
        assert response.status_code == 403, (path, response.status_code)
    assert client.get("/v1/admin/users/invites", headers=headers).status_code == 403


def test_an_api_token_can_never_write(client, people):
    # Even the owner's token with every scope a token may carry.
    headers = people.token(people.owner, ["ask", "voice", "actions", "admin.read"])
    assert client.get("/v1/admin/overview", headers=headers).status_code == 200
    for method, path, body in WRITES:
        response = call(client, method, path, body, headers)
        assert response.status_code == 403, (path, response.status_code)
    pin = {"password": PASSWORD, "pin": "2468"}
    assert client.put("/v1/me/pin", json=pin, headers=headers).status_code == 403


def test_a_cookie_session_needs_the_csrf_header_for_console_writes(client, people):
    login = {"email": "owner@example.com", "password": PASSWORD}
    assert client.post("/v1/auth/login", json=login).status_code == 200
    body = {"email": "new@example.com", "role": "staff"}
    assert client.post("/v1/admin/users/invites", json=body).status_code == 403
    evil = {"X-Ira-Request": "1", "Origin": "https://evil.example.com"}
    assert client.post("/v1/admin/users/invites", json=body, headers=evil).status_code == 403
    ok = client.post("/v1/admin/users/invites", json=body, headers={"X-Ira-Request": "1"})
    assert ok.status_code == 200


# Users and invitations.


def test_invite_by_link_sets_a_password_and_signs_in(client, runtime, people):
    owner = people.session(people.owner)
    created = client.post(
        "/v1/admin/users/invites", json={"email": "New@Example.com", "role": "staff"}, headers=owner
    ).json()
    token = created["token"]
    assert created["path"] == f"/admin/invite#token={token}"
    assert created["invite"]["email"] == "new@example.com"
    stored = runtime.store.one("SELECT token_hash FROM invites")
    assert token not in stored["token_hash"]  # only the hash is kept

    listed = client.get("/v1/admin/users/invites", headers=owner).json()
    assert [i["email"] for i in listed] == ["new@example.com"]
    assert "token" not in listed[0]

    invitee = TestClient(client.app)
    lookup = invitee.post("/v1/invites/lookup", json={"token": token})
    assert lookup.json() == {**lookup.json(), "email": "new@example.com", "role": "staff"}
    weak = invitee.post("/v1/invites/accept", json={"token": token, "password": "short"})
    assert weak.status_code == 400
    accepted = invitee.post("/v1/invites/accept", json={"token": token, "password": PASSWORD})
    assert accepted.status_code == 200
    assert accepted.json()["user"]["role"] == "staff"
    assert invitee.get("/v1/auth/me").json()["user"]["email"] == "new@example.com"

    used = invitee.post("/v1/invites/accept", json={"token": token, "password": PASSWORD})
    assert used.status_code == 410
    assert client.get("/v1/admin/users/invites", headers=owner).json() == []
    whats = [c["what"] for c in changes(client, people)]
    assert whats[:2] == ["user.joined", "user.invited"]


def test_invites_expire_after_72_hours_and_can_be_withdrawn(client, runtime, people):
    owner = people.session(people.owner)
    body = {"email": "late@example.com", "role": "viewer"}
    token = client.post("/v1/admin/users/invites", json=body, headers=owner).json()["token"]
    runtime.accounts.clock = lambda: 10**10  # far in the future
    assert client.post("/v1/invites/lookup", json={"token": token}).status_code == 410
    runtime.accounts.clock = __import__("time").time

    second = client.post("/v1/admin/users/invites", json=body, headers=owner).json()
    # The newer invite replaced the first one.
    assert client.post("/v1/invites/lookup", json={"token": token}).status_code == 410
    invite_id = second["invite"]["id"]
    assert client.delete(f"/v1/admin/users/invites/{invite_id}", headers=owner).status_code == 200
    gone = client.post("/v1/invites/lookup", json={"token": second["token"]})
    assert gone.status_code == 410
    assert client.delete(f"/v1/admin/users/invites/{invite_id}", headers=owner).status_code == 404


def test_inviting_an_existing_user_or_a_bad_role_is_refused(client, people):
    owner = people.session(people.owner)
    taken = {"email": "desk@example.com", "role": "staff"}
    assert client.post("/v1/admin/users/invites", json=taken, headers=owner).status_code == 400
    bad = {"email": "x@example.com", "role": "superuser"}
    assert client.post("/v1/admin/users/invites", json=bad, headers=owner).status_code == 400


def test_changing_a_role_is_recorded_before_and_after(client, people):
    owner = people.session(people.owner)
    response = client.patch(
        f"/v1/admin/users/{people.staff.id}", json={"role": "admin"}, headers=owner
    )
    assert response.json()["role"] == "admin"
    latest = changes(client, people)[0]
    assert latest["what"] == "user.role" and latest["target"] == "desk@example.com"
    assert (latest["before"], latest["after"]) == ("staff", "admin")
    assert latest["actor"] == "owner@example.com via web"


def test_the_last_owner_cannot_be_removed_or_demoted(client, runtime, people):
    owner = people.session(people.owner)
    me = people.owner.id
    demote = client.patch(f"/v1/admin/users/{me}", json={"role": "admin"}, headers=owner)
    assert demote.status_code == 409
    assert client.delete(f"/v1/admin/users/{me}", headers=owner).status_code == 409
    assert runtime.accounts.get_user(me).role == "owner"

    # With a second owner, the first may step down.
    second = client.patch(
        f"/v1/admin/users/{people.admin.id}", json={"role": "owner"}, headers=owner
    )
    assert second.status_code == 200
    assert client.patch(f"/v1/admin/users/{me}", json={"role": "admin"}, headers=owner).is_success


def test_removing_a_user_ends_their_sessions_and_tokens(client, runtime, people):
    owner = people.session(people.owner)
    session = people.session(people.staff)
    token = people.token(people.staff, ["ask"])
    assert client.get("/v1/auth/me", headers=session).status_code == 200

    assert client.delete(f"/v1/admin/users/{people.staff.id}", headers=owner).status_code == 200
    assert client.get("/v1/auth/me", headers=session).status_code == 401
    assert client.post("/v1/ask", json={"text": "hi"}, headers=token).status_code == 401
    emails = [u["email"] for u in client.get("/v1/admin/users", headers=owner).json()]
    assert "desk@example.com" not in emails

    # Inviting the same email again brings the account back, history and all.
    body = {"email": "desk@example.com", "role": "viewer"}
    invite = client.post("/v1/admin/users/invites", json=body, headers=owner).json()
    accept = {"token": invite["token"], "password": PASSWORD}
    back = TestClient(client.app).post("/v1/invites/accept", json=accept).json()
    assert back["user"]["id"] == people.staff.id and back["user"]["role"] == "viewer"


def test_resetting_a_pin_makes_the_user_set_a_new_one(client, runtime, people):
    owner = people.session(people.owner)
    runtime.guard.set_pin("2468", user_id=people.staff.id)
    rows = {u["email"]: u for u in client.get("/v1/admin/users", headers=owner).json()}
    assert rows["desk@example.com"]["has_pin"] is True

    reset = client.post(f"/v1/admin/users/{people.staff.id}/reset-pin", headers=owner)
    assert reset.status_code == 200
    staff = people.session(people.staff)
    assert client.get("/v1/me/pin", headers=staff).json()["has_pin"] is False
    assert changes(client, people)[0]["what"] == "user.pin_reset"

    wrong = client.put(
        "/v1/me/pin", json={"password": WRONG_PASSWORD, "pin": "1357"}, headers=staff
    )
    assert wrong.status_code == 403
    ok = client.put("/v1/me/pin", json={"password": PASSWORD, "pin": "1357"}, headers=staff)
    assert ok.status_code == 200
    assert client.get("/v1/me/pin", headers=staff).json()["has_pin"] is True
    bad = client.put("/v1/me/pin", json={"password": PASSWORD, "pin": "12ab"}, headers=staff)
    assert bad.status_code == 422


def test_a_viewer_cannot_set_a_pin(client, people):
    viewer = people.session(people.viewer)
    body = {"password": PASSWORD, "pin": "1357"}
    assert client.put("/v1/me/pin", json=body, headers=viewer).status_code == 403
    assert client.get("/v1/me/pin", headers=viewer).json()["can_confirm"] is False


# Tokens.


def test_tokens_are_shown_once_and_can_be_revoked(client, people):
    admin = people.session(people.admin)
    created = client.post(
        "/v1/admin/tokens", json={"label": "phone", "scopes": ["ask", "voice"]}, headers=admin
    ).json()
    token = created["token"]
    assert token.startswith("ira_t_") and created["scopes"] == ["ask", "voice"]
    listing = client.get("/v1/admin/tokens", headers=admin).text
    assert token not in listing and "phone" in listing

    use = {"Authorization": f"Bearer {token}"}
    assert client.post("/v1/ask", json={"text": "hi"}, headers=use).status_code == 200
    assert client.delete(f"/v1/admin/tokens/{created['id']}", headers=admin).status_code == 200
    assert client.post("/v1/ask", json={"text": "hi"}, headers=use).status_code == 401
    assert client.delete(f"/v1/admin/tokens/{created['id']}", headers=admin).status_code == 404
    latest = changes(client, people)[0]
    assert latest["what"] == "token.revoked" and token not in str(latest)


def test_token_scopes_are_checked(client, people):
    admin = people.session(people.admin)
    for scopes in (["admin.write"], ["users"], [], ["nonsense"]):
        body = {"label": "x", "scopes": scopes}
        response = client.post("/v1/admin/tokens", json=body, headers=admin)
        assert response.status_code in (400, 422), scopes
