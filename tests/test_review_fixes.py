"""Findings of the 2 Nov review that were not about tainted turns, each pinned here."""

from __future__ import annotations

from typing import Any

import pytest

from ira import accounts as accounts_module
from ira.accounts import AccountError, LoginLimiter
from ira.channels.me import export_data
from ira.channels.telegram import MAX_WAITING_UPDATES, next_offset
from ira.connectors.google import Google
from ira.models.base import ChatResponse, StreamDone, TextDelta
from ira.models.fake import ScriptedProvider
from ira.models.gateway import Gateway
from ira.tools.registry import ToolError

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
pytestmark = pytest.mark.anyio


def test_an_export_goes_by_the_person_not_an_email_someone_else_had():
    runtime = make_runtime(provider=ScriptedProvider())
    first = runtime.accounts.create_first_owner("first@example.com", PASSWORD)
    runtime.store.execute(
        "INSERT INTO pending_actions (id, tool, params, summary, tier, status, created_at, "
        "expires_at, user_id, actor, conversation_id) "
        "VALUES ('a1', 't', '{}', 'theirs', 2, 'executed', 1, 2, ?, 'second@example.com', 'c')",
        (first.id,),
    )
    token, _ = runtime.accounts.create_invite("second@example.com", "staff", "first@example.com")
    second = runtime.accounts.accept_invite(token, PASSWORD)

    class Who:
        user = second

    exported = export_data(runtime, Who())  # type: ignore[arg-type]
    assert "theirs" not in str(exported)


def test_a_garbage_invite_token_costs_no_hash(monkeypatch: pytest.MonkeyPatch):
    runtime = make_runtime(provider=ScriptedProvider())
    runtime.accounts.create_first_owner("owner@example.com", PASSWORD)

    class NoHash:
        def hash(self, _: str) -> str:
            raise AssertionError("hashed before checking the token")

    monkeypatch.setattr(accounts_module, "_hasher", NoHash())
    with pytest.raises(AccountError, match="not valid"):
        runtime.accounts.accept_invite("made-up", PASSWORD)


def test_looking_at_the_limiter_grows_nothing():
    limiter = LoginLimiter()
    for n in range(1000):
        assert not limiter.blocked(f"user{n}@example.com")
    assert limiter._attempts == {}


def test_a_blocked_address_trying_new_emails_grows_nothing():
    limiter = LoginLimiter()
    for n in range(5):
        assert limiter.take("1.2.3.4", f"user{n}@example.com") is not None
    size = len(limiter._attempts)
    for n in range(1000):
        assert limiter.take("1.2.3.4", f"other{n}@example.com") is None
    assert len(limiter._attempts) == size


def test_the_limiter_still_blocks_and_forgets():
    now = [0.0]
    limiter = LoginLimiter(clock=lambda: now[0])
    for _ in range(5):
        limiter.fail("a")
    assert limiter.blocked("a")
    now[0] = 1000
    assert not limiter.blocked("a") and limiter._attempts == {}


class Odd(ScriptedProvider):
    """Raises what a provider should not: an expired credential's own error type."""

    async def chat(self, *args: Any, **options: Any) -> ChatResponse:
        raise RuntimeError("token expired secret-abc")

    async def stream(self, *args: Any, **options: Any):
        raise RuntimeError("token expired secret-abc")
        yield  # pragma: no cover


async def test_a_turn_falls_to_the_next_model_on_any_error():
    gateway = Gateway(
        {"odd": Odd(), "good": ScriptedProvider(["Hello"])}, {"default": ["odd:m", "good:m"]}
    )
    answer = await gateway.chat([], None)
    assert answer.text == "Hello" and answer.model == "good:m"


async def test_a_stream_falls_to_the_next_model_on_any_error():
    gateway = Gateway(
        {"odd": Odd(), "good": ScriptedProvider(["Hello"])}, {"default": ["odd:m", "good:m"]}
    )
    events = [event async for event in gateway.stream([], None)]
    assert isinstance(events[-1], StreamDone) and events[-1].response.model == "good:m"
    assert any(isinstance(e, TextDelta) for e in events)


async def test_an_unexpected_error_never_carries_its_text():
    gateway = Gateway({"odd": Odd()}, {"default": ["odd:m"]})
    with pytest.raises(Exception) as caught:
        await gateway.chat([], None)
    assert "secret-abc" not in str(caught.value)


class FakeGoogle(Google):
    def __init__(self, failing: set[str]) -> None:
        self.failing = failing
        self.urls: list[str] = []

    async def get(self, url: str, token: str, params: dict[str, Any] | None = None) -> Any:
        self.urls.append(url)
        if url.endswith("calendarList"):
            holidays = "en.indian#holiday@group.v.calendar.google.com"
            return {"items": [{"id": "me@example.com", "summary": "Me"}, {"id": holidays}]}
        if any(f in url for f in self.failing):
            raise ToolError("Google answered HTTP 404")
        return {"items": [{"summary": "Dentist", "start": {"date": "2026-11-05"}}]}


async def test_a_calendar_id_is_escaped_and_one_failing_loses_only_itself():
    google = FakeGoogle({"holiday"})
    found = await google.calendar_events("token", None, None, None)
    assert any("en.indian%23holiday" in url for url in google.urls)
    assert not any("#" in url for url in google.urls)
    assert [e["title"] for e in found["events"]] == ["Dentist"]


async def test_every_calendar_failing_is_no_empty_calendar():
    google = FakeGoogle({"/calendars/"})
    with pytest.raises(ToolError):
        await google.calendar_events("token", None, None, None)


def test_the_next_poll_keeps_updates_being_handled_until_there_are_too_many():
    assert next_offset({5, 7}, 9) == 5
    assert next_offset(set(), 9) == 10
    assert next_offset(set(), 0) is None
    many = set(range(100, 100 + MAX_WAITING_UPDATES))
    assert next_offset(many, 200) == 201
