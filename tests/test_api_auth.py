"""HTTP auth: who may call which route, with which credential."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ira.accounts import AccountError
from ira.channels.http import create_app
from ira.models.fake import ScriptedProvider
from ira.voice.providers import FakeSTT, FakeTTS

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"


@pytest.fixture
def runtime(registry):
    return make_runtime(
        provider=ScriptedProvider(["answer"] * 20),
        registry=registry,
        stt=FakeSTT(),
        tts=FakeTTS(),
    )


@pytest.fixture
def client(runtime):
    with TestClient(create_app(runtime, start_channels=False)) as test_client:
        yield test_client


@pytest.fixture
def owner(runtime):
    return runtime.accounts.create_first_owner("owner@example.com", PASSWORD)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def token_for(runtime, user, scopes: list[str]) -> str:
    token, _ = runtime.accounts.create_token(user, "test", scopes)
    return token


def test_public_routes_need_no_credential(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/sw.js").status_code == 200
    assert client.get("/v1/auth/status").json()["setup_required"] is True
    assert client.get("/v1/openapi.json").status_code == 200


def test_every_api_route_rejects_anonymous_calls(client):
    for method, path in [
        ("get", "/v1/info"),
        ("post", "/v1/ask"),
        ("post", "/v1/ask/stream"),
        ("post", "/v1/voice/transcribe"),
        ("post", "/v1/voice/speak"),
        ("post", "/v1/actions/act_x/confirm"),
        ("post", "/v1/actions/act_x/cancel"),
        ("get", "/v1/admin/overview"),
        ("get", "/v1/admin/calls"),
        ("get", "/v1/auth/me"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 401, (method, path, response.status_code)


def test_a_phone_token_may_only_ask(client, runtime, owner):
    headers = bearer(token_for(runtime, owner, ["ask"]))

    assert client.post("/v1/ask", json={"text": "hi"}, headers=headers).status_code == 200
    assert client.get("/v1/info", headers=headers).status_code == 200
    for method, path, body in [
        ("post", "/v1/voice/speak", {"text": "hi"}),
        ("post", "/v1/actions/act_x/confirm", {"pin": "1234"}),
        ("post", "/v1/actions/act_x/cancel", None),
        ("get", "/v1/admin/overview", None),
        ("get", "/v1/admin/audit", None),
    ]:
        kwargs = {"headers": headers}
        if body is not None:
            kwargs["json"] = body
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 403, (path, response.status_code)


def test_token_scopes_cannot_exceed_the_role(runtime, owner):
    staff = runtime.accounts.create_user("staff@example.com", PASSWORD, "staff")
    with pytest.raises(AccountError):
        runtime.accounts.create_token(staff, "x", ["admin.read"])
    with pytest.raises(AccountError):
        runtime.accounts.create_token(owner, "x", ["users"])  # never on a token


def test_revoked_and_unknown_tokens_are_rejected(client, runtime, owner):
    token = token_for(runtime, owner, ["ask"])
    runtime.accounts.revoke_token("test")
    assert client.post("/v1/ask", json={"text": "hi"}, headers=bearer(token)).status_code == 401
    unknown = bearer("ira_t_not-a-real-token")
    assert client.post("/v1/ask", json={"text": "hi"}, headers=unknown).status_code == 401


def test_roles_decide_admin_access(client, runtime, owner):
    viewer = runtime.accounts.create_user("viewer@example.com", PASSWORD, "viewer")
    staff = runtime.accounts.create_user("staff@example.com", PASSWORD, "staff")
    viewer_session, _ = runtime.accounts.start_session(viewer)
    staff_session, _ = runtime.accounts.start_session(staff)

    assert client.get("/v1/admin/overview", headers=bearer(viewer_session)).status_code == 200
    assert (
        client.post("/v1/ask", json={"text": "hi"}, headers=bearer(viewer_session)).status_code
        == 403
    )
    assert client.get("/v1/admin/overview", headers=bearer(staff_session)).status_code == 403
    assert (
        client.post("/v1/ask", json={"text": "hi"}, headers=bearer(staff_session)).status_code
        == 200
    )


def test_cookie_sessions_need_the_csrf_header_to_change_things(client, owner):
    login = client.post("/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
    assert login.status_code == 200
    assert login.json()["session_token"] is None  # cookie only
    assert "httponly" in login.headers["set-cookie"].lower()

    assert client.get("/v1/info").status_code == 200  # reads are fine
    assert client.post("/v1/ask", json={"text": "hi"}).status_code == 403
    ok = client.post("/v1/ask", json={"text": "hi"}, headers={"X-Ira-Request": "1"})
    assert ok.status_code == 200

    client.post("/v1/auth/logout", headers={"X-Ira-Request": "1"})
    assert client.get("/v1/info").status_code == 401


def test_login_without_cookie_returns_a_bearer_session(client, owner):
    response = client.post(
        "/v1/auth/login",
        json={"email": "owner@example.com", "password": PASSWORD, "use_cookie": False},
    )
    token = response.json()["session_token"]
    assert token.startswith("ira_s_")
    assert "set-cookie" not in response.headers
    me = client.get("/v1/auth/me", headers=bearer(token)).json()
    assert me["user"]["role"] == "owner"


def test_repeated_wrong_passwords_are_throttled(client, owner):
    for _ in range(5):
        wrong = client.post(
            "/v1/auth/login", json={"email": "owner@example.com", "password": "nope"}
        )
        assert wrong.status_code == 401
    right = client.post("/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
    assert right.status_code == 429


def test_setup_needs_the_code_and_works_only_once(client, runtime):
    code = runtime.setup_code
    assert code  # created at startup because no user exists
    body = {"email": "first@example.com", "password": PASSWORD, "setup_code": "WRONG-CODE"}
    assert client.post("/v1/auth/setup", json=body).status_code == 403

    body["setup_code"] = code
    created = client.post("/v1/auth/setup", json=body)
    assert created.status_code == 200
    assert created.json()["user"]["role"] == "owner"

    body["email"] = "second@example.com"
    assert client.post("/v1/auth/setup", json=body).status_code == 409


def test_conversations_are_private_to_their_user(client, runtime, owner):
    other = runtime.accounts.create_user("other@example.com", PASSWORD, "staff")
    mine, theirs = token_for(runtime, owner, ["ask"]), token_for(runtime, other, ["ask"])

    client.post(
        "/v1/ask", json={"text": "secret plan", "conversation_id": "c1"}, headers=bearer(mine)
    )
    client.post("/v1/ask", json={"text": "hello", "conversation_id": "c1"}, headers=bearer(theirs))

    ids = {row["id"] for row in runtime.conversations.recent()}
    assert ids == {f"http:{owner.id}:c1", f"http:{other.id}:c1"}


def test_cookie_writes_from_another_site_are_refused(client, owner):
    login = client.post("/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
    assert "samesite=strict" in login.headers["set-cookie"].lower()
    body = {"text": "hi"}

    header = {"X-Ira-Request": "1"}
    evil = {**header, "Origin": "https://evil.example.com"}
    assert client.post("/v1/ask", json=body, headers=evil).status_code == 403
    cross = {**header, "Sec-Fetch-Site": "cross-site"}
    assert client.post("/v1/ask", json=body, headers=cross).status_code == 403
    sibling = {**header, "Sec-Fetch-Site": "same-site"}
    assert client.post("/v1/ask", json=body, headers=sibling).status_code == 403

    same = {**header, "Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}
    assert client.post("/v1/ask", json=body, headers=same).status_code == 200
    assert client.post("/v1/ask", json=body, headers=header).status_code == 200
    # Behind a proxy that rewrites Host, the original host arrives as X-Forwarded-Host.
    proxied = {**header, "Origin": "https://ira.example.com", "X-Forwarded-Host": "ira.example.com"}
    assert client.post("/v1/ask", json=body, headers=proxied).status_code == 200


def test_a_bearer_session_needs_no_csrf_header(client, runtime, owner):
    session, _ = runtime.accounts.start_session(owner)
    evil = {**bearer(session), "Origin": "https://evil.example.com"}
    assert client.post("/v1/ask", json={"text": "hi"}, headers=evil).status_code == 200


def test_info_says_whether_the_browser_may_recognise_speech(registry):
    runtime = make_runtime(registry=registry)
    user = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    token, _ = runtime.accounts.create_token(user, "script", ["ask"])
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app(runtime, start_channels=False)) as client:
        info = client.get("/v1/info", headers=headers).json()
        assert (info["stt"], info["browser_stt"], info["mic_language"]) == (
            None,
            "fallback",
            "hi-IN",
        )
        runtime.assistant.user_settings.set(user.id, "languages", ["en"])
        assert client.get("/v1/info", headers=headers).json()["mic_language"] == "en-IN"
        runtime.settings.voice.browser_stt = "off"
        assert client.get("/v1/info", headers=headers).json()["browser_stt"] == "off"


def test_info_says_whether_a_live_call_works_here(registry):
    from ira.voice.providers import FakeSTT, FakeTTS

    runtime = make_runtime(registry=registry)
    user = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    voice, _ = runtime.accounts.create_token(user, "phone", ["ask", "voice"])
    typing, _ = runtime.accounts.create_token(user, "script", ["ask"])
    with TestClient(create_app(runtime, start_channels=False)) as client:

        def live(token: str) -> bool:
            headers = {"Authorization": f"Bearer {token}"}
            return client.get("/v1/info", headers=headers).json()["live"]

        assert live(voice) is False  # no speech-to-text or voice on this server
        runtime.stt, runtime.tts = FakeSTT(), FakeTTS()
        assert live(voice) is True
        assert live(typing) is False  # a token without voice


def test_without_the_connectors_extra_everything_else_works(registry, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "mcp", None)  # as if the extra were not installed
    runtime = make_runtime(registry=registry)
    runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        body = {"email": "owner@example.com", "password": PASSWORD, "use_cookie": False}
        token = client.post("/v1/auth/login", json=body).json()["session_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/v1/me/connections", headers=headers).json() == {
            "available": False,
            "connections": [],
            "servers": [],
            "builtins": [],
        }
        made = client.post(
            "/v1/me/connections", json={"name": "x", "url": "https://a.example"}, headers=headers
        )
        assert made.status_code == 501 and "connectors extra" in made.json()["detail"]
        assert client.post("/v1/ask", json={"text": "hello"}, headers=headers).status_code == 200


def test_many_sign_ins_at_once_cannot_beat_the_limit(monkeypatch):
    """Guesses sent together are counted before the password check, not after."""
    import threading
    import time as _time

    from ira.accounts import Accounts

    runtime = make_runtime()
    runtime.accounts.create_first_owner("owner@example.com", "correct-horse-battery")
    checked: list[str] = []
    real = Accounts.authenticate

    def slow(self, email, password):
        checked.append(password)
        _time.sleep(0.02)
        return real(self, email, password)

    monkeypatch.setattr(Accounts, "authenticate", slow)
    client = TestClient(create_app(runtime, start_channels=False))
    codes: list[int] = []

    def guess(n: int) -> None:
        body = {"email": "owner@example.com", "password": f"guess-{n}", "use_cookie": False}
        codes.append(client.post("/v1/auth/login", json=body).status_code)

    threads = [threading.Thread(target=guess, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(checked) <= 5 and codes.count(429) >= 15  # five tries, then the limit

    # A right password gives its attempt back: signing in often is never blocked.
    fresh = make_runtime()
    fresh.accounts.create_first_owner("owner@example.com", "correct-horse-battery")
    other = TestClient(create_app(fresh, start_channels=False))
    body = {"email": "owner@example.com", "password": "correct-horse-battery", "use_cookie": False}
    assert [other.post("/v1/auth/login", json=body).status_code for _ in range(7)] == [200] * 7
