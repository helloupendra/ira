"""The console's Telegram routes, against a fake Bot API: the bot, pairing, unpairing."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.channels.telegram import TelegramBot, TelegramError

from .conftest import make_runtime
from .test_telegram import FakeBotApi

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
FAKE_TOKEN = "123456:TEST-token-value"  # pragma: allowlist secret
CHAT = {"id": 5550100, "type": "private", "first_name": "Riley", "last_name": "Demo",
        "username": "rileydemo"}  # fmt: skip


class FakeTelegram(FakeBotApi):
    """The Bot API as the console uses it: getMe, counted."""

    def __init__(self, username: str = "clinic_ira_bot") -> None:
        super().__init__()
        self.username = username
        self.fail = False
        self.get_me_calls = 0

    async def get_me(self) -> dict:
        self.get_me_calls += 1
        if self.fail:
            raise TelegramError("getMe: Unauthorized")
        return {"id": 1, "is_bot": True, "username": self.username}


@pytest.fixture
def world(registry, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, FAKE_TOKEN)
    runtime = make_runtime(registry=registry)
    runtime.telegram_api = FakeTelegram()
    accounts = runtime.accounts
    people = {
        "owner": accounts.create_first_owner("owner@example.com", PASSWORD),
        "admin": accounts.create_user("manager@example.com", PASSWORD, "admin"),
        "staff": accounts.create_user("desk@example.com", PASSWORD, "staff"),
        "viewer": accounts.create_user("books@example.com", PASSWORD, "viewer"),
    }

    def session(role: str) -> dict[str, str]:
        token, _ = accounts.start_session(people[role])
        return {"Authorization": f"Bearer {token}"}

    with TestClient(create_app(runtime, start_channels=False)) as client:
        yield client, session, runtime, people


async def send(runtime, text: str, message_id: int = 1, chat: dict = CHAT) -> None:
    bot = TelegramBot(runtime, runtime.telegram_api)
    update = {"message_id": message_id, "chat": chat, "text": text}
    await bot.handle_update({"update_id": message_id, "message": update})


def test_the_bot_is_named_from_get_me_once_an_hour(world):
    client, session, runtime, _ = world
    viewer = session("viewer")  # reading needs admin.read only
    first = client.get("/v1/admin/telegram", headers=viewer).json()
    assert first["bot_username"] == "clinic_ira_bot"
    assert first["bot_link"] == "https://t.me/clinic_ira_bot"
    assert first["token_present"] is True and first["enabled"] is False
    assert first["token_env"] == TOKEN_ENV and first["pairing_seconds"] == 600
    assert first["chats"] == [] and first["running"] is False
    client.get("/v1/admin/telegram", headers=viewer)
    assert runtime.telegram_api.get_me_calls == 1  # cached
    assert FAKE_TOKEN not in str(first)


def test_without_a_token_telegram_is_never_asked(world, monkeypatch):
    client, session, runtime, _ = world
    monkeypatch.delenv(TOKEN_ENV)
    view = client.get("/v1/admin/telegram", headers=session("owner")).json()
    assert view["token_present"] is False
    assert view["bot_username"] is None and view["bot_link"] is None
    assert runtime.telegram_api.get_me_calls == 0


def test_a_failed_get_me_says_why_and_is_tried_again(world):
    client, session, runtime, _ = world
    runtime.telegram_api.fail = True
    view = client.get("/v1/admin/telegram", headers=session("owner")).json()
    assert view["bot_username"] is None and view["bot_error"] == "getMe: Unauthorized"
    client.get("/v1/admin/telegram", headers=session("owner"))
    assert runtime.telegram_api.get_me_calls == 1  # not hammered

    runtime.telegram_api.fail = False
    runtime.channel_state["telegram_bot"]["until"] = time.time() - 1  # a minute later
    view = client.get("/v1/admin/telegram", headers=session("owner")).json()
    assert view["bot_username"] == "clinic_ira_bot" and view["bot_error"] is None


@pytest.mark.anyio
async def test_pair_list_and_unpair_a_chat_with_the_change_log(world):
    client, session, runtime, people = world
    owner = session("owner")
    before = time.time()
    pairing = client.post("/v1/admin/telegram/pairing", headers=owner).json()
    assert pairing["command"] == f"/pair {pairing['code']}" and len(pairing["code"]) == 8
    assert before + 600 <= pairing["expires_at"] <= time.time() + 600
    assert pairing["email"] == "owner@example.com"
    assert pairing["bot_link"] == "https://t.me/clinic_ira_bot"

    await send(runtime, pairing["command"])
    assert runtime.telegram_api.sent()[-1].startswith("Paired")
    chats = client.get("/v1/admin/telegram", headers=owner).json()["chats"]
    assert len(chats) == 1
    chat = chats[0]
    assert chat["chat_id"] == CHAT["id"] and chat["name"] == "Riley Demo (@rileydemo)"
    assert (chat["email"], chat["role"], chat["user_id"]) == (
        "owner@example.com",
        "owner",
        people["owner"].id,
    )

    gone = client.delete(f"/v1/admin/telegram/chats/{CHAT['id']}", headers=owner)
    assert gone.status_code == 200
    assert client.get("/v1/admin/telegram", headers=owner).json()["chats"] == []
    again = client.delete(f"/v1/admin/telegram/chats/{CHAT['id']}", headers=owner)
    assert again.status_code == 404

    log = client.get("/v1/admin/changes", headers=owner).json()
    assert [c["what"] for c in log[:2]] == ["telegram.unpaired", "telegram.pairing_started"]
    assert log[0]["target"] == str(CHAT["id"])
    assert log[0]["before"] == {"user": "owner@example.com", "name": "Riley Demo (@rileydemo)"}
    assert log[1]["target"] == "owner@example.com"
    assert log[1]["after"] == {"expires_at": pairing["expires_at"]}
    assert pairing["code"] not in str(log)  # the code is a secret

    # An unpaired chat gets nothing from the model.
    await send(runtime, "hello", message_id=2)
    assert "private" in runtime.telegram_api.sent()[-1]


def test_who_may_start_a_pairing(world):
    client, session, runtime, people = world
    path = "/v1/admin/telegram/pairing"
    mine = client.post(path, json={}, headers=session("admin"))
    assert mine.status_code == 200 and mine.json()["email"] == "manager@example.com"
    for_owner = {"user_id": people["owner"].id}
    assert client.post(path, json=for_owner, headers=session("admin")).status_code == 403
    for_staff = client.post(path, json={"user_id": people["staff"].id}, headers=session("owner"))
    assert for_staff.status_code == 200 and for_staff.json()["email"] == "desk@example.com"
    assert client.post(path, json={"user_id": 999}, headers=session("owner")).status_code == 404
    for role in ("staff", "viewer"):
        assert client.post(path, headers=session(role)).status_code == 403, role
    token, _ = runtime.accounts.create_token(people["owner"], "phone", ["admin.read"])
    phone = {"Authorization": f"Bearer {token}"}
    assert client.post(path, headers=phone).status_code == 403
    assert client.get("/v1/admin/telegram", headers=phone).status_code == 200


@pytest.mark.anyio
async def test_a_chat_paired_before_names_were_kept_gets_one_on_its_next_message(world):
    client, session, runtime, people = world
    runtime.store.execute(
        "INSERT INTO telegram_chats (chat_id, user_id, paired_at) VALUES (?, ?, 1)",
        (CHAT["id"], people["owner"].id),
    )
    owner = session("owner")
    assert client.get("/v1/admin/telegram", headers=owner).json()["chats"][0]["name"] is None
    await send(runtime, "/help")
    chats = client.get("/v1/admin/telegram", headers=owner).json()["chats"]
    assert chats[0]["name"] == "Riley Demo (@rileydemo)"
