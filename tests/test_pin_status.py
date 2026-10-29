"""GET /v1/me/pin: the PIN rule, when the PIN was set, and when a lock ends."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider
from ira.security import PIN_MAX_LENGTH, PIN_MIN_LENGTH

from .conftest import FAST_PIN_ITERATIONS, make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
REFUND = ChatResponse(
    text="", tool_calls=[ToolCall("c", "refund", '{"order_id": "A1", "amount": 5}')]
)


@pytest.fixture
def world(registry):
    runtime = make_runtime(provider=ScriptedProvider([REFUND, "ok"] * 3), registry=registry)
    runtime.guard.pin_iterations = FAST_PIN_ITERATIONS
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    session, _ = runtime.accounts.start_session(owner)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        yield client, {"Authorization": f"Bearer {session}"}, runtime, owner


def test_the_pin_rule_comes_from_one_place(world):
    client, headers, _, _ = world
    status = client.get("/v1/me/pin", headers=headers).json()
    assert (status["pin_min_length"], status["pin_max_length"]) == (4, 12)
    assert (status["pin_min_length"], status["pin_max_length"]) == (PIN_MIN_LENGTH, PIN_MAX_LENGTH)
    schema = client.get("/v1/openapi.json").json()["components"]["schemas"]
    pin = schema["PinSetRequest"]["properties"]["pin"]
    assert (pin["minLength"], pin["maxLength"]) == (PIN_MIN_LENGTH, PIN_MAX_LENGTH)
    assert pin["pattern"] == r"^\d{4,12}$"
    too_long = {"password": PASSWORD, "pin": "1" * (PIN_MAX_LENGTH + 1)}
    assert client.put("/v1/me/pin", json=too_long, headers=headers).status_code == 422


def test_pin_set_at_is_when_the_pin_was_set_and_null_for_older_pins(world):
    client, headers, runtime, owner = world
    assert client.get("/v1/me/pin", headers=headers).json()["pin_set_at"] is None

    before = time.time()
    body = {"password": PASSWORD, "pin": "2468"}
    assert client.put("/v1/me/pin", json=body, headers=headers).status_code == 200
    status = client.get("/v1/me/pin", headers=headers).json()
    assert status["has_pin"] and before <= status["pin_set_at"] <= time.time()

    # A PIN from before IRA recorded the moment.
    runtime.store.execute("UPDATE users SET pin_set_at = NULL WHERE id = ?", (owner.id,))
    status = client.get("/v1/me/pin", headers=headers).json()
    assert status["has_pin"] and status["pin_set_at"] is None


def test_locked_until_comes_with_locked_seconds(world):
    client, headers, runtime, owner = world
    runtime.guard.set_pin("2468", user_id=owner.id)
    status = client.get("/v1/me/pin", headers=headers).json()
    assert status["locked_until"] is None and status["locked_seconds"] is None

    for _ in range(runtime.guard.max_wrong_pins):
        action = client.post("/v1/ask", json={"text": "refund A1"}, headers=headers).json()
        outcome = client.post(
            f"/v1/actions/{action['action']['id']}/confirm", json={"pin": "0000"}, headers=headers
        ).json()
    assert outcome["status"] == "locked"
    until = runtime.guard.locked_until(owner.id)
    assert outcome["locked_until"] == until

    status = client.get("/v1/me/pin", headers=headers).json()
    assert status["locked_until"] == until
    assert abs(status["locked_seconds"] - (until - time.time())) <= 1
    security = client.get("/v1/admin/security", headers=headers).json()
    assert security["locked_until"] == until
