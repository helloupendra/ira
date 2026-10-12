"""The admin console's write API: who may change what, and what gets recorded."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.config import Settings
from ira.models.base import ChatResponse, ProviderError, ToolCall
from ira.models.fake import ScriptedProvider
from ira.overrides import apply as apply_overrides
from ira.runtime import build_runtime
from ira.store import Store
from ira.tools.registry import ToolRegistry
from ira.voice.providers import FakeTTS

from .conftest import FAST_PIN_ITERATIONS, make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
WRONG_PASSWORD = "not-my-password"  # pragma: allowlist secret
# Names of environment variables, not keys.
CLOUD_KEY_ENV = "IRA_TEST_CLOUD_KEY"  # pragma: allowlist secret
SPARE_KEY_ENV = "IRA_TEST_SPARE_KEY"  # pragma: allowlist secret


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
    ("patch", "/v1/admin/tools/order_status", {"enabled": False}),
    ("post", "/v1/admin/tools/order_status/test", {"params": {"order_id": "A1"}}),
    ("post", "/v1/admin/models/test", {"ref": "fake:m"}),
    ("put", "/v1/admin/models/tiers/default", {"order": None}),
    ("patch", "/v1/admin/settings", {"name": "Sunny"}),
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
    # ...but can make the changes an admin is for.
    response = call(client, "patch", "/v1/admin/settings", {"name": "Sunny"}, headers)
    assert response.status_code == 200


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


def test_the_role_table_matches_what_the_server_enforces(client, people):
    roles = client.get("/v1/admin/roles", headers=people.session(people.viewer)).json()
    table = {r["role"]: set(r["permissions"]) for r in roles}
    assert "users" in table["owner"] and "users" not in table["admin"]
    assert table["viewer"] == {"admin.read"}
    assert all(r["description"] for r in roles)


def test_every_route_documents_its_shapes(client):
    spec = client.get("/v1/openapi.json").json()
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            assert operation.get("summary"), (method, path)
            assert operation["operationId"].replace("_", "").isalnum(), (method, path)
    write = spec["paths"]["/v1/admin/users/invites"]["post"]["responses"]
    assert "403" in write and "ErrorDetail" in str(write["403"])


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


# Tools.


def test_switching_a_tool_off_hides_it_from_the_model_and_persists(client, runtime, people):
    admin = people.session(people.admin)
    switched = client.patch(
        "/v1/admin/tools/order_status", json={"enabled": False}, headers=admin
    ).json()
    assert switched["enabled"] is False
    assert "order_status" not in [s["name"] for s in runtime.registry.schemas()]
    names = [t["name"] for t in client.get("/v1/info", headers=admin).json()["tools"]]
    assert "order_status" not in names

    # A fresh registry picks the switch up from the database.
    fresh = ToolRegistry()

    @fresh.tool
    def order_status(order_id: str) -> dict:
        """Look up an order."""
        return {}

    again = make_runtime(store=runtime.store, registry=fresh)
    apply_overrides(again)
    assert not fresh.is_enabled("order_status")

    client.patch("/v1/admin/tools/order_status", json={"enabled": True}, headers=admin)
    assert runtime.registry.is_enabled("order_status")
    whats = [(c["what"], c["after"]) for c in changes(client, people)[:2]]
    assert whats == [("tool.enabled", True), ("tool.enabled", False)]
    missing = client.patch("/v1/admin/tools/nope", json={"enabled": False}, headers=admin)
    assert missing.status_code == 404


def test_a_read_tool_can_be_tested_but_an_action_never(client, people, ledger):
    admin = people.session(people.admin)
    ok = client.post(
        "/v1/admin/tools/order_status/test", json={"params": {"order_id": "A1"}}, headers=admin
    ).json()
    assert ok["ok"] is True and ok["result"] == {"order_id": "A1", "status": "shipped"}

    invalid = client.post(
        "/v1/admin/tools/order_status/test", json={"params": {"nope": 1}}, headers=admin
    ).json()
    assert invalid["ok"] is False and "invalid parameters" in invalid["error"]

    action = client.post(
        "/v1/admin/tools/refund/test",
        json={"params": {"order_id": "A1", "amount": 5}},
        headers=admin,
    )
    assert action.status_code == 409
    assert ledger.refunds == []
    assert client.post("/v1/admin/tools/nope/test", json={}, headers=admin).status_code == 404


def test_tools_show_who_may_confirm_actions(client, people):
    tools = {
        t["name"]: t
        for t in client.get("/v1/admin/tools", headers=people.session(people.viewer)).json()
    }
    assert tools["refund"]["confirm_roles"] == ["owner", "admin", "staff"]
    assert tools["order_status"]["confirm_roles"] is None


# Models.


@pytest.fixture
def two_model_runtime():
    settings = Settings.model_validate(
        {
            "data_dir": "unused",
            "models": {
                "providers": {"a": {"type": "fake"}, "b": {"type": "fake"}},
                "tiers": {"default": ["a:router", "b:router"], "fast": ["b:router"]},
            },
        }
    )
    return build_runtime(settings, registry=ToolRegistry(), store=Store(":memory:"))


def test_a_tier_can_be_reordered_and_reset(two_model_runtime):
    runtime = two_model_runtime
    people = People(runtime)
    admin = people.session(people.admin)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        view = client.get("/v1/admin/models", headers=admin).json()
        default = next(t for t in view["tiers"] if t["name"] == "default")
        assert default["chain"] == ["a:router", "b:router"] and not default["overridden"]

        body = {"order": ["b:router", "a:router"]}
        moved = client.put("/v1/admin/models/tiers/default", json=body, headers=admin).json()
        assert moved["chain"] == ["b:router", "a:router"] and moved["overridden"]
        assert runtime.gateway.chain("default") == ["b:router", "a:router"]
        assert runtime.settings.models.tiers["default"] == ["a:router", "b:router"]

        for wrong in (["a:router"], ["a:router", "a:router"], ["a:router", "c:router"]):
            response = client.put(
                "/v1/admin/models/tiers/default", json={"order": wrong}, headers=admin
            )
            assert response.status_code == 400, wrong
        unknown = client.put("/v1/admin/models/tiers/nope", json={"order": None}, headers=admin)
        assert unknown.status_code == 404

        # A restart keeps the order; a reset goes back to ira.yaml.
        again = build_runtime(runtime.settings, registry=ToolRegistry(), store=runtime.store)
        assert again.gateway.chain("default") == ["b:router", "a:router"]
        reset = client.put("/v1/admin/models/tiers/default", json={"order": None}, headers=admin)
        assert reset.json()["chain"] == ["a:router", "b:router"]
        latest = changes(client, people)[1]
        assert latest["what"] == "model.chain"
        assert latest["before"] == ["a:router", "b:router"]


def test_testing_a_model_reports_ok_and_latency(client, runtime, people):
    admin = people.session(people.admin)
    result = client.post("/v1/admin/models/test", json={"ref": "fake:m"}, headers=admin).json()
    assert result["ok"] is True and result["text"] == "ready" and result["seconds"] >= 0
    call = runtime.store.one("SELECT * FROM calls ORDER BY id DESC LIMIT 1")
    assert call["purpose"] == "test"
    unknown = client.post("/v1/admin/models/test", json={"ref": "fake:other"}, headers=admin)
    assert unknown.status_code == 404


def test_a_failing_model_test_says_why(client, runtime, people):
    runtime.gateway.providers["fake"] = ScriptedProvider([ProviderError("busy", kind="capacity")])
    admin = people.session(people.admin)
    result = client.post("/v1/admin/models/test", json={"ref": "fake:m"}, headers=admin).json()
    assert result["ok"] is False and result["error_kind"] == "capacity"


def test_keys_show_presence_never_values(two_model_runtime, monkeypatch):
    settings = Settings.model_validate(
        {
            "data_dir": "unused",
            "models": {
                "providers": {
                    "demo": {"type": "fake"},
                    "cloud": {"type": "openai", "api_key_env": CLOUD_KEY_ENV},
                    "spare": {"type": "anthropic", "api_key_env": SPARE_KEY_ENV},
                },
                "tiers": {"default": ["demo:router"]},
            },
        }
    )
    monkeypatch.setenv(CLOUD_KEY_ENV, "value-that-must-not-leak")
    monkeypatch.delenv(SPARE_KEY_ENV, raising=False)
    runtime = build_runtime(settings, registry=ToolRegistry(), store=Store(":memory:"))
    people = People(runtime)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        viewer = people.session(people.viewer)
        keys = client.get("/v1/admin/keys", headers=viewer)
        models = client.get("/v1/admin/models", headers=viewer)
    assert {k["env"]: k["present"] for k in keys.json()} == {
        CLOUD_KEY_ENV: True,
        SPARE_KEY_ENV: False,
    }
    assert "value-that-must-not-leak" not in keys.text + models.text
    providers = {p["name"]: p for p in models.json()["providers"]}
    assert providers["spare"]["in_use"] is False and providers["demo"]["auth"] == "none"


# Settings.


def test_the_name_and_voice_override_the_config_and_reset(client, runtime, people):
    admin = people.session(people.admin)
    view = client.get("/v1/admin/settings", headers=admin).json()
    assert view["name"] == {"value": "Ira", "default": "Ira", "overridden": False, "editable": True}

    changed = client.patch(
        "/v1/admin/settings", json={"name": "Sunny", "voice": "nova"}, headers=admin
    ).json()
    assert changed["name"]["value"] == "Sunny" and changed["name"]["overridden"]
    assert changed["voice"]["value"] == "nova" and runtime.tts.voice == "nova"
    assert runtime.assistant.name == "Sunny"

    # Only the field sent changes; null goes back to the config.
    reset = client.patch("/v1/admin/settings", json={"name": None}, headers=admin).json()
    assert reset["name"]["value"] == "Ira" and not reset["name"]["overridden"]
    assert reset["voice"]["value"] == "nova"
    whats = [c["what"] for c in changes(client, people)[:3]]
    assert whats == ["settings.name", "settings.voice", "settings.name"]


def test_the_voice_cannot_be_set_without_text_to_speech(registry):
    runtime = make_runtime(registry=registry)
    people = People(runtime)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        admin = people.session(people.admin)
        view = client.get("/v1/admin/settings", headers=admin).json()
        assert view["voice"]["editable"] is False
        response = client.patch("/v1/admin/settings", json={"voice": "nova"}, headers=admin)
        assert response.status_code == 400


# Actions, security and costs.


def test_actions_show_who_confirmed_and_the_confirm_roles(registry):
    provider = ScriptedProvider(
        [
            ChatResponse(
                text="", tool_calls=[ToolCall("c", "refund", '{"order_id": "A1", "amount": 5}')]
            ),
            "ok",
        ]
    )
    runtime = make_runtime(provider=provider, registry=registry)
    runtime.guard.tool_confirm_roles = {"refund": ("owner",)}
    people = People(runtime)
    runtime.guard.set_pin("2468", user_id=people.owner.id)
    runtime.guard.set_pin("1357", user_id=people.staff.id)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        staff, owner = people.session(people.staff), people.session(people.owner)
        reply = client.post("/v1/ask", json={"text": "refund A1"}, headers=staff).json()
        action_id = reply["action"]["id"]
        refused = client.post(
            f"/v1/actions/{action_id}/confirm", json={"pin": "1357"}, headers=staff
        )
        assert refused.status_code == 403 and refused.json()["status"] == "not_allowed"
        done = client.post(f"/v1/actions/{action_id}/confirm", json={"pin": "2468"}, headers=owner)
        assert done.json()["status"] == "executed"

        rows = client.get("/v1/admin/actions", headers=owner).json()
        assert rows[0]["actor"] == "desk@example.com via web"
        assert rows[0]["decided_by"] == "owner@example.com via web"
        security = client.get("/v1/admin/security", headers=owner).json()
        assert security["action_rules"] == [{"tool": "refund", "confirm_roles": ["owner"]}]
        assert security["cookie_samesite"] == "strict"
        assert "manager@example.com" in security["users_without_pin"]
        costs = client.get("/v1/admin/costs?days=7", headers=owner).json()
        assert costs[0]["calls"] == 2


def sse_events(response) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_a_proposed_action_says_who_may_confirm_it(registry):
    refund = ChatResponse(
        text="", tool_calls=[ToolCall("c", "refund", '{"order_id": "A1", "amount": 5}')]
    )
    runtime = make_runtime(provider=ScriptedProvider([refund, "ok"] * 4), registry=registry)
    runtime.guard.tool_confirm_roles = {"refund": ("owner", "admin")}
    people = People(runtime)
    ask = {"text": "refund A1"}
    with TestClient(create_app(runtime, start_channels=False)) as client:
        # A staff member may propose it, but their role cannot confirm it.
        staff = client.post("/v1/ask", json=ask, headers=people.session(people.staff)).json()
        assert staff["action"]["confirm_roles"] == ["owner", "admin"]
        assert staff["action"]["can_confirm"] is False

        streamed = client.post("/v1/ask/stream", json=ask, headers=people.session(people.owner))
        action = next(e["action"] for e in sse_events(streamed) if e["type"] == "action")
        assert action["confirm_roles"] == ["owner", "admin"] and action["can_confirm"] is True

        # The owner's phone token may ask but not confirm, so it cannot confirm this either.
        phone = people.token(people.owner, ["ask"])
        assert (
            client.post("/v1/ask", json=ask, headers=phone).json()["action"]["can_confirm"] is False
        )

        # Without a per-tool rule, actions.confirm_roles applies.
        runtime.guard.tool_confirm_roles = {}
        staff = client.post("/v1/ask", json=ask, headers=people.session(people.staff)).json()
        assert staff["action"]["confirm_roles"] == ["owner", "admin", "staff"]
        assert staff["action"]["can_confirm"] is True
        cancelled = client.post(
            f"/v1/actions/{staff['action']['id']}/cancel", headers=people.session(people.staff)
        ).json()
        assert cancelled["action"]["status"] == "cancelled"
        assert cancelled["action"]["confirm_roles"] == ["owner", "admin", "staff"]


def test_ask_shows_each_tool_call_with_a_capped_result(registry):
    @registry.tool
    def read_notes(day: str) -> str:
        """Read a day's notes."""
        return "n" * 2000

    notes = ChatResponse(text="", tool_calls=[ToolCall("c1", "read_notes", '{"day": "today"}')])
    runtime = make_runtime(provider=ScriptedProvider([notes, "ok"] * 2), registry=registry)
    people = People(runtime)
    headers = people.token(people.staff, ["ask"])
    with TestClient(create_app(runtime, start_channels=False)) as client:
        reply = client.post("/v1/ask", json={"text": "notes?"}, headers=headers).json()
        assert reply["tools_used"] == ["read_notes"]
        (call,) = reply["tool_calls"]
        assert call["id"] == "c1" and call["arguments"] == {"day": "today"} and call["ok"]
        assert call["truncated"] and call["result"] == "n" * 500 + "…"

        streamed = client.post("/v1/ask/stream", json={"text": "notes?"}, headers=headers)
        events = sse_events(streamed)
        assert [e["type"] for e in events][:3] == ["start", "tool", "tool_result"]
        tool, result = events[1], events[2]
        assert tool == {
            "type": "tool",
            "id": "c1",
            "name": "read_notes",
            "arguments": {"day": "today"},
        }
        assert result["id"] == "c1" and result["ok"] is True and result["truncated"] is True
        assert len(result["result"]) == 501 and result["result"].endswith("…")
        assert events[-1]["type"] == "done"


# The caller's own conversations.


def test_callers_read_only_their_own_conversations(registry):
    runtime = make_runtime(provider=ScriptedProvider(["answer"] * 10), registry=registry)
    people = People(runtime)
    phone = people.token(people.owner, ["ask"])  # a phone token can read its own history
    staff = people.session(people.staff)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        for text in ("is Tuesday free", "and Wednesday"):
            client.post("/v1/ask", json={"text": text, "conversation_id": "kitchen"}, headers=phone)
        client.post("/v1/ask", json={"text": "hello", "conversation_id": "hall"}, headers=phone)
        client.post("/v1/ask", json={"text": "desk only", "conversation_id": "desk"}, headers=staff)
        # A row that records no user stays visible only through the admin API.
        runtime.conversations.ensure(f"http:{people.owner.id}:legacy", channel="api", user_id=None)

        mine = client.get("/v1/conversations", headers=phone).json()
        assert [c["id"] for c in mine] == ["hall", "kitchen"]
        kitchen = mine[1]
        assert kitchen["channel"] == "api" and kitchen["turns"] == 2
        assert kitchen["preview"] == "is Tuesday free"
        older = client.get(f"/v1/conversations?before={mine[0]['last_at']}", headers=phone)
        assert [c["id"] for c in older.json()] == ["kitchen"]
        assert len(client.get("/v1/conversations?limit=1", headers=phone).json()) == 1

        transcript = client.get("/v1/conversations/kitchen", headers=phone).json()
        assert [m["role"] for m in transcript] == ["user", "assistant", "user", "assistant"]
        assert transcript[0]["content"] == "is Tuesday free"

        # Someone else's conversation is not found, by its id or by its internal key.
        assert client.get("/v1/conversations/kitchen", headers=staff).status_code == 404
        internal = f"/v1/conversations/http:{people.owner.id}:kitchen"
        assert client.get(internal, headers=staff).status_code == 404
        assert client.get("/v1/conversations/desk", headers=phone).status_code == 404
        assert client.get("/v1/conversations/legacy", headers=phone).status_code == 404
        assert [c["id"] for c in client.get("/v1/conversations", headers=staff).json()] == ["desk"]

        # A viewer cannot ask, so has no conversations of their own to read.
        viewer = people.session(people.viewer)
        assert client.get("/v1/conversations", headers=viewer).status_code == 403


# Sessions.

LAPTOP = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) Firefox/131.0"


def current_session_id(client, headers) -> str:
    rows = client.get("/v1/me/sessions", headers=headers).json()
    return next(r["id"] for r in rows if r["current"])


def test_people_see_and_end_their_own_sessions(client, runtime, people):
    login = {"email": "owner@example.com", "password": PASSWORD}
    assert client.post("/v1/auth/login", json=login, headers={"User-Agent": LAPTOP}).is_success
    csrf = {"X-Ira-Request": "1"}  # the laptop signs in with the cookie
    phone = people.session(people.owner)
    staff = people.session(people.staff)

    listed = client.get("/v1/me/sessions")
    rows = listed.json()
    assert len(rows) == 2
    laptop = next(r for r in rows if r["current"])
    assert laptop["user_agent"] == LAPTOP and laptop["expires_at"] > laptop["created_at"]
    assert set(laptop) == {
        "id",
        "created_at",
        "last_used_at",
        "expires_at",
        "current",
        "user_agent",
    }
    assert "ira_s_" not in listed.text and "token" not in listed.text
    phone_id = current_session_id(client, phone)
    assert phone_id != laptop["id"]

    # Someone else's session is not found; a cookie write needs the CSRF header.
    staff_id = current_session_id(client, staff)
    assert client.delete(f"/v1/me/sessions/{staff_id}", headers=csrf).status_code == 404
    assert client.delete(f"/v1/me/sessions/{phone_id}").status_code == 403
    assert client.delete(f"/v1/me/sessions/{phone_id}", headers=csrf).status_code == 200
    assert client.get("/v1/auth/me", headers=phone).status_code == 401
    assert client.get("/v1/auth/me", headers=staff).status_code == 200
    latest = changes(client, people)[0]
    assert latest["what"] == "session.revoked" and latest["target"] == phone_id
    assert latest["before"] == {"user": "owner@example.com"}

    # Sign out everywhere else, keeping this session.
    others = [people.session(people.owner) for _ in range(2)]
    count = len(client.get("/v1/me/sessions").json()) - 1  # changes() signed in too
    ended = client.post("/v1/me/sessions/revoke-others", headers=csrf).json()
    assert ended == {"ended": count} and count >= 2
    assert all(client.get("/v1/auth/me", headers=h).status_code == 401 for h in others)
    assert [r["current"] for r in client.get("/v1/me/sessions").json()] == [True]
    latest = changes(client, people)[0]
    assert latest["what"] == "session.revoked_others" and latest["after"] == {"ended": count}
    assert client.get("/v1/auth/me", headers=staff).status_code == 200

    # Ending this session signs the laptop out.
    gone = client.delete(f"/v1/me/sessions/{laptop['id']}", headers=csrf)
    assert gone.status_code == 200 and "ira_session=" in gone.headers["set-cookie"]
    assert client.get("/v1/auth/me").status_code == 401


def test_a_phone_token_reads_its_conversations_but_not_sessions(client, people):
    phone = people.token(people.owner, ["ask"])
    assert client.post("/v1/ask", json={"text": "hi"}, headers=phone).status_code == 200
    assert len(client.get("/v1/conversations", headers=phone).json()) == 1
    assert client.get("/v1/me/sessions", headers=phone).status_code == 403
    assert client.post("/v1/me/sessions/revoke-others", headers=phone).status_code == 403
    assert client.delete("/v1/me/sessions/ses_x", headers=phone).status_code == 403


def test_only_the_owner_sees_and_ends_everyone_s_sessions(client, people):
    staff = people.session(people.staff)
    staff_id = current_session_id(client, staff)
    for user in (people.admin, people.staff, people.viewer):
        headers = people.session(user)
        assert client.get("/v1/admin/sessions", headers=headers).status_code == 403, user.role
        gone = client.delete(f"/v1/admin/sessions/{staff_id}", headers=headers)
        assert gone.status_code == 403, user.role
    owner_token = people.token(people.owner, ["ask", "voice", "actions", "admin.read"])
    assert client.get("/v1/admin/sessions", headers=owner_token).status_code == 403

    owner = people.session(people.owner)
    listed = client.get("/v1/admin/sessions", headers=owner)
    rows = {r["id"]: r for r in listed.json()}
    assert rows[staff_id]["email"] == "desk@example.com" and not rows[staff_id]["current"]
    assert rows[staff_id]["user_id"] == people.staff.id
    assert sum(r["current"] for r in rows.values()) == 1
    assert "ira_s_" not in listed.text

    assert client.delete(f"/v1/admin/sessions/{staff_id}", headers=owner).status_code == 200
    assert client.get("/v1/auth/me", headers=staff).status_code == 401
    assert client.delete(f"/v1/admin/sessions/{staff_id}", headers=owner).status_code == 404
    latest = changes(client, people)[0]
    assert latest["what"] == "session.revoked" and latest["actor"] == "owner@example.com via web"
    assert latest["before"] == {"user": "desk@example.com"}
