"""Learning from what a person says, with the quote check, and thumbs on answers."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.learning.extract import checked, extract
from ira.models.fake import ScriptedProvider

from .conftest import make_runtime

pytestmark = pytest.mark.anyio

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret


def test_the_quote_check():
    said = "Main office se nikal raha hoon, 20 min mein ghar"
    assert checked(said, "office se nikal raha hoon", "office", set()) == "Office"
    # The quote must be their own words, and the place must be in it or already named.
    assert checked(said, "office se nikal gaya hoon", "office", set()) is None
    assert checked(said, "office se nikal raha hoon", "gym", set()) is None
    assert checked(said, "20 min mein ghar", "Home", {"Home"}) == "Home"
    assert checked(said, "", "office", set()) is None
    assert checked("पहुँच गया ऑफिस", "पहुँच गया ऑफिस", "ऑफिस", set()) == "ऑफिस"


def person(runtime, *sources):
    user = runtime.accounts.create_user("owner@example.com", PASSWORD, "owner")
    if sources:
        runtime.assistant.user_settings.set(user.id, "learning", True)
        runtime.assistant.user_settings.set(user.id, "learning_sources", list(sources))
    return user


def reply(*items):
    return json.dumps({"observations": list(items)})


async def test_only_with_conversation_on_and_only_for_movement_words():
    provider = ScriptedProvider()
    runtime = make_runtime(provider=provider)
    user = person(runtime, "phone")
    said = "office se nikal raha hoon"
    assert await extract(runtime.learning, runtime.gateway, user.id, said, tier="default") == []
    runtime.assistant.user_settings.set(user.id, "learning_sources", ["conversation"])
    quiet = "aaj ki khabar batao"
    assert await extract(runtime.learning, runtime.gateway, user.id, quiet, tier="default") == []
    assert provider.calls == []  # no model was asked either time


async def test_invented_quotes_and_places_are_dropped():
    provider = ScriptedProvider(
        [
            reply(
                {"kind": "leave", "place": "office", "quote": "office se nikal raha hoon"},
                {"kind": "arrive", "place": "Gym", "quote": "gym pahunch gaya"},
                {"kind": "teleport", "place": "office", "quote": "office"},
            )
        ]
    )
    runtime = make_runtime(provider=provider)
    user = person(runtime, "conversation")
    said = "office se nikal raha hoon, thodi der mein"
    ids = await extract(runtime.learning, runtime.gateway, user.id, said, tier="default")
    assert len(ids) == 1
    (row,) = runtime.learning.data.observations(user.id)
    assert (row["kind"], row["source"], row["label"]) == ("leave", "conversation", "Office")
    assert row["detail"] == {"quote": "office se nikal raha hoon"}


async def test_a_finished_turn_is_learned_from_in_the_background():
    provider = ScriptedProvider(
        [
            "Theek hai, safe jaana!",
            reply({"kind": "heading", "place": "ghar", "quote": "ghar ja raha hoon"}),
        ]
    )
    runtime = make_runtime(provider=provider)
    user = person(runtime, "conversation")
    answer = await runtime.assistant.ask("ghar ja raha hoon", conversation_id="c1", user_id=user.id)
    assert answer.text == "Theek hai, safe jaana!" and answer.message_id
    await asyncio.gather(*runtime.assistant._background)
    (row,) = runtime.learning.data.observations(user.id)
    assert (row["kind"], row["label"]) == ("heading", "Ghar")


def test_thumbs_on_answers_are_kept_only_with_feedback_on():
    provider = ScriptedProvider(["आपके Chrome में 3 टैब खुले हैं।"])
    runtime = make_runtime(provider=provider)
    owner = person(runtime)
    runtime.accounts.create_user("staff@example.com", PASSWORD, "staff")

    def login(client, email):
        body = {"email": email, "password": PASSWORD, "use_cookie": False}
        token = client.post("/v1/auth/login", json=body).json()["session_token"]
        return {"Authorization": f"Bearer {token}"}

    with TestClient(create_app(runtime, start_channels=False)) as client:
        mine, theirs = login(client, "owner@example.com"), login(client, "staff@example.com")
        asked = client.post(
            "/v1/ask", json={"text": "tabs?", "conversation_id": "c1"}, headers=mine
        ).json()
        thumb = {"message_id": asked["message_id"], "rating": "up"}
        assert client.post("/v1/me/feedback", json=thumb, headers=mine).json() == {"learned": False}
        settings = runtime.assistant.user_settings
        settings.set(owner.id, "learning", True)
        settings.set(owner.id, "learning_sources", ["feedback"])
        noted = {**thumb, "note": "  shorter please  "}
        assert client.post("/v1/me/feedback", json=noted, headers=mine).json() == {"learned": True}
        assert client.post("/v1/me/feedback", json=thumb, headers=theirs).status_code == 404
        wrong = {**thumb, "message_id": asked["message_id"] - 1}  # their own question
        assert client.post("/v1/me/feedback", json=wrong, headers=mine).status_code == 404
    (row,) = runtime.learning.data.observations(owner.id)
    assert row["kind"] == "feedback"
    assert row["detail"] == {
        "rating": "up",
        "language": "hi",
        "chars": len("आपके Chrome में 3 टैब खुले हैं।"),
        "message_id": asked["message_id"],
        "note": "shorter please",
    }
