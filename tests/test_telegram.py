"""The Telegram channel against a fake Bot API: pairing, PIN deletion, voice notes."""

from __future__ import annotations

import pytest

from ira.channels.telegram import TelegramApi, TelegramBot, create_pairing_code
from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider
from ira.voice.providers import FakeSTT, FakeTTS

from .conftest import make_runtime

pytestmark = pytest.mark.anyio

CHAT = 5550100
PASSWORD = "correct-horse-battery"
PIN = "4321"


class FakeBotApi:
    """Records every Bot API call the bot makes."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.files: dict[str, bytes] = {}

    async def send_message(self, chat_id, text):
        self.calls.append(("sendMessage", chat_id, text))

    async def delete_message(self, chat_id, message_id):
        self.calls.append(("deleteMessage", chat_id, message_id))

    async def send_voice(self, chat_id, mp3):
        self.calls.append(("sendVoice", chat_id, len(mp3)))

    async def download_file(self, file_id):
        self.calls.append(("getFile", file_id))
        return self.files[file_id]

    def sent(self) -> list[str]:
        return [c[2] for c in self.calls if c[0] == "sendMessage"]

    def deleted(self) -> list[int]:
        return [c[2] for c in self.calls if c[0] == "deleteMessage"]


def update(text: str | None = None, message_id: int = 1, chat_type: str = "private", **extra):
    message = {"message_id": message_id, "chat": {"id": CHAT, "type": chat_type}, **extra}
    if text is not None:
        message["text"] = text
    return {"update_id": message_id, "message": message}


@pytest.fixture
def provider():
    return ScriptedProvider()


@pytest.fixture
def runtime(registry, provider):
    rt = make_runtime(provider=provider, registry=registry, stt=FakeSTT(), tts=FakeTTS())
    rt.guard.set_pin(PIN)
    return rt


@pytest.fixture
def owner(runtime):
    return runtime.accounts.create_first_owner("owner@example.com", PASSWORD)


@pytest.fixture
def api():
    return FakeBotApi()


@pytest.fixture
def bot(runtime, api):
    return TelegramBot(runtime, api)


async def pair(bot, runtime, owner) -> None:
    code = create_pairing_code(runtime.store, owner.id)
    await bot.handle_update(update(f"/pair {code}", message_id=99))


async def test_unpaired_chats_get_nothing_from_the_model(bot, api, provider):
    await bot.handle_update(update("what are my appointments?"))
    assert provider.calls == []
    assert "private" in api.sent()[-1]


async def test_pairing_is_one_time_and_deletes_the_code(bot, api, runtime, owner):
    code = create_pairing_code(runtime.store, owner.id)
    await bot.handle_update(update(f"/pair {code}", message_id=7))
    assert api.deleted() == [7]
    assert api.sent()[-1].startswith("Paired")

    other = TelegramBot(runtime, FakeBotApi())
    second = {"update_id": 8, "message": {"message_id": 8, "chat": {"id": 1, "type": "private"}}}
    second["message"]["text"] = f"/pair {code}"
    await other.handle_update(second)
    assert "not valid" in other.api.sent()[-1]


async def test_group_chats_are_ignored(bot, api, runtime, owner):
    await pair(bot, runtime, owner)
    api.calls.clear()
    await bot.handle_update(update("hello", chat_type="group"))
    assert api.calls == []


async def test_a_typed_pin_is_deleted_and_never_sent_to_a_model(
    bot, api, runtime, owner, provider, ledger
):
    await pair(bot, runtime, owner)
    provider.script = [
        ChatResponse(
            text="", tool_calls=[ToolCall("c1", "refund", '{"order_id": "A1", "amount": 9}')]
        ),
        "I've proposed the refund. Type your PIN to confirm.",
    ]
    await bot.handle_update(update("refund A1 by 9", message_id=10))
    assert any(text.startswith("Proposed: Refund 9 on order A1") for text in api.sent())
    model_calls_before = len(provider.calls)

    await bot.handle_update(update(PIN, message_id=11))

    assert 11 in api.deleted()
    first_delete = next(
        i for i, c in enumerate(api.calls) if c[0] == "deleteMessage" and c[2] == 11
    )
    first_reply_after = next(
        i for i, c in enumerate(api.calls) if i > first_delete and c[0] == "sendMessage"
    )
    assert first_delete < first_reply_after  # deleted before anything else is said
    assert api.sent()[-1].startswith("Done: Refund 9 on order A1")
    assert ledger.refunds == [("A1", 9)]
    assert len(provider.calls) == model_calls_before
    every_message_sent_to_models = [m.text for call in provider.calls for m in call["messages"]]
    assert all(PIN not in text for text in every_message_sent_to_models)


async def test_a_pin_with_nothing_pending_is_still_deleted(bot, api, runtime, owner, provider):
    await pair(bot, runtime, owner)
    await bot.handle_update(update("98765", message_id=20))
    assert 20 in api.deleted()
    assert "No action is waiting" in api.sent()[-1]
    assert provider.calls == []


async def test_voice_note_is_transcribed_answered_and_spoken(
    bot, api, runtime, owner, provider, monkeypatch
):
    await pair(bot, runtime, owner)
    monkeypatch.setattr("ira.channels.telegram.ogg_to_wav", lambda data: b"RIFF-fake-wav")
    api.files["voice-1"] = b"OggS-fake"
    provider.script = ["We open at nine."]

    await bot.handle_update(update(message_id=30, voice={"file_id": "voice-1", "duration": 3}))

    assert runtime.stt.received == [b"RIFF-fake-wav"]
    assert api.sent()[-1] == 'Heard: "what are your opening hours"\n\nWe open at nine.'
    assert any(c[0] == "sendVoice" for c in api.calls)
    assert runtime.tts.spoken == ["We open at nine."]


async def test_a_spoken_pin_is_deleted_and_not_used(
    bot, api, runtime, owner, provider, monkeypatch
):
    await pair(bot, runtime, owner)
    monkeypatch.setattr("ira.channels.telegram.ogg_to_wav", lambda data: b"RIFF")
    runtime.stt.text = "4321"
    api.files["v"] = b"OggS"

    await bot.handle_update(update(message_id=40, voice={"file_id": "v", "duration": 2}))

    assert 40 in api.deleted()
    assert "type the PIN" in api.sent()[-1]
    assert provider.calls == []


async def test_name_command_renames_for_owner_but_not_staff(bot, api, runtime, owner):
    await pair(bot, runtime, owner)
    await bot.handle_update(update("/name Nova", message_id=50))
    assert runtime.assistant.name == "Nova"
    assert api.sent()[-1] == "Done. Call me Nova."

    staff = runtime.accounts.create_user("staff@example.com", PASSWORD, "staff")
    code = create_pairing_code(runtime.store, staff.id)
    staff_bot = TelegramBot(runtime, FakeBotApi())
    pair_msg = {"update_id": 1, "message": {"message_id": 1, "chat": {"id": 42, "type": "private"}}}
    pair_msg["message"]["text"] = f"/pair {code}"
    await staff_bot.handle_update(pair_msg)
    rename = {"update_id": 2, "message": {"message_id": 2, "chat": {"id": 42, "type": "private"}}}
    rename["message"]["text"] = "/name Hal"
    await staff_bot.handle_update(rename)
    assert runtime.assistant.name == "Nova"
    assert "Only an owner or admin" in staff_bot.api.sent()[-1]


async def test_cancel_command_drops_the_pending_action(bot, api, runtime, owner, provider, ledger):
    await pair(bot, runtime, owner)
    provider.script = [
        ChatResponse(
            text="", tool_calls=[ToolCall("c1", "refund", '{"order_id": "B2", "amount": 3}')]
        ),
        "Proposed.",
    ]
    await bot.handle_update(update("refund B2", message_id=60))
    await bot.handle_update(update("/cancel", message_id=61))
    assert api.sent()[-1].startswith("Cancelled")
    await bot.handle_update(update(PIN, message_id=62))
    assert ledger.refunds == []


async def test_bot_api_errors_never_contain_the_token():
    import httpx

    token = "123456:TEST-token-value"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    api = TelegramApi(token, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    from ira.channels.telegram import TelegramError

    with pytest.raises(TelegramError) as caught:
        await api.send_message(1, "hi")
    assert token not in str(caught.value)
