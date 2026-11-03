"""Findings of the 2 Nov review that were not about tainted turns, each pinned here."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ira import accounts as accounts_module
from ira.accounts import AccountError, LoginLimiter
from ira.approvals import open_refusal
from ira.channels.http import SWAGGER_CSS_HASH, SWAGGER_JS_HASH, create_app
from ira.channels.me import export_data
from ira.channels.telegram import MAX_WAITING_UPDATES, next_offset
from ira.connectors.google import Google
from ira.connectors.mcp import _private
from ira.drop import DropError
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


def http_client(runtime: Any) -> TestClient:
    return TestClient(create_app(runtime, start_channels=False))


def test_the_docs_page_pins_its_script_and_cannot_be_framed(tmp_path: Path):
    client = http_client(make_runtime(provider=ScriptedProvider(), data_dir=tmp_path))
    page = client.get("/v1/docs")
    assert page.status_code == 200
    assert "swagger-ui-dist@5.32.0/swagger-ui-bundle.js" in page.text
    assert (
        f'integrity="{SWAGGER_JS_HASH}"' in page.text
        and f'integrity="{SWAGGER_CSS_HASH}"' in page.text
    )
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"


def sign_in_token(runtime: Any) -> str:
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    token, _ = runtime.accounts.create_token(owner, "t", ["ask", "voice", "drop"])
    return token


def test_a_drop_past_the_limit_stops_before_it_is_read_whole(tmp_path: Path):
    runtime = make_runtime(provider=ScriptedProvider(), data_dir=tmp_path)
    runtime.drop.max_file_bytes = 1000
    client = http_client(runtime)
    headers = {"Authorization": f"Bearer {sign_in_token(runtime)}"}
    too_big = client.post(
        "/v1/me/drop", headers=headers, files={"file": ("a.txt", b"x" * 100_000, "text/plain")}
    )
    assert too_big.status_code == 413


def test_a_text_past_the_limit_is_refused(tmp_path: Path):
    runtime = make_runtime(provider=ScriptedProvider(), data_dir=tmp_path)
    client = http_client(runtime)
    headers = {
        "Authorization": f"Bearer {sign_in_token(runtime)}",
        "content-type": "application/json",
    }
    answer = client.post(
        "/v1/me/drop", headers=headers, content=b'{"text":"' + b"x" * 2_000_000 + b'"}'
    )
    assert answer.status_code == 413


def test_uploads_under_way_count_against_the_quota(tmp_path: Path):
    runtime = make_runtime(provider=ScriptedProvider(), data_dir=tmp_path)
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    runtime.drop.quota_bytes = 1000
    runtime.drop._arriving[owner.id] = 900
    with pytest.raises(DropError):
        runtime.drop.add_file(
            owner.id, io.BytesIO(b"x" * 200), "a.txt", "text/plain", from_label="Web"
        )
    assert runtime.drop._arriving[owner.id] == 900
    runtime.drop._arriving.clear()
    item = runtime.drop.add_file(
        owner.id, io.BytesIO(b"x" * 200), "a.txt", "text/plain", from_label="Web"
    )
    assert item.size == 200 and runtime.drop._arriving == {}


@pytest.mark.parametrize(
    "name", ["a.pyz", "a.ahk", "a.au3", "a.msu", "a.jnlp", "a.scf", "a.docm", "a.xlsm"]
)
def test_files_that_run_something_are_never_opened(name: str):
    assert open_refusal("file_open", {"path": f"~/Downloads/{name}"})


def test_a_document_opens():
    assert open_refusal("file_open", {"path": "~/Downloads/invoice.pdf"}) is None


def test_the_headers_say_what_the_pages_may_use(tmp_path: Path):
    client = http_client(make_runtime(provider=ScriptedProvider(), data_dir=tmp_path))
    plain = client.get("/healthz")
    assert "microphone=(self)" in plain.headers["permissions-policy"]
    assert "camera=()" in plain.headers["permissions-policy"]
    assert "strict-transport-security" not in plain.headers
    secure = client.get("/healthz", headers={"x-forwarded-proto": "https"})
    assert "max-age" in secure.headers["strict-transport-security"]


async def test_a_pins_lock_grows_until_the_right_pin(tmp_path: Path):
    now = [1000.0]
    runtime = make_runtime(provider=ScriptedProvider(), data_dir=tmp_path)
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    guard = runtime.guard
    guard.clock = lambda: now[0]

    async def wrong() -> bool:
        return False

    async def right() -> bool:
        return True

    waits = []
    for _ in range(3):
        for _ in range(guard.max_wrong_pins):
            verdict, until = await guard._checked(owner.id, wrong)
        assert verdict == "wrong_locked"
        waits.append(until - now[0])
        now[0] = until + 1
    assert waits == [guard.lock_seconds, guard.lock_seconds * 2, guard.lock_seconds * 4]
    assert (await guard._checked(owner.id, right))[0] == "ok"
    for _ in range(guard.max_wrong_pins):
        verdict, until = await guard._checked(owner.id, wrong)
    assert until - now[0] == guard.lock_seconds


def test_a_label_several_people_use_needs_to_say_whose(tmp_path: Path):
    runtime = make_runtime(provider=ScriptedProvider(), data_dir=tmp_path)
    accounts = runtime.accounts
    first = accounts.create_first_owner("first@example.com", PASSWORD)
    invite, _ = accounts.create_invite("second@example.com", "staff", "first@example.com")
    second = accounts.accept_invite(invite, PASSWORD)
    accounts.create_token(first, "phone", ["ask"])
    accounts.create_token(second, "phone", ["ask"])
    with pytest.raises(AccountError, match="several people"):
        accounts.revoke_token("phone")
    assert accounts.revoke_token("phone", "first@example.com") == 1
    assert accounts.revoke_token("phone") == 1


@pytest.mark.parametrize("address", ["100.64.0.1", "10.0.0.1", "127.0.0.1", "169.254.1.1"])
def test_addresses_not_on_the_internet_are_private(address: str):
    assert _private(address)


def test_an_internet_address_is_not_private():
    assert not _private("93.184.216.34")
