"""Drop on Telegram: /drop puts text or a file in the inbox, and new items from the
person's other devices come to their chat, unless they switch it off."""

from __future__ import annotations

import asyncio
import io
import os

import pytest
from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.channels.telegram import TelegramBot, create_pairing_code, drop_notifier

from .conftest import make_runtime
from .test_telegram import CHAT, PASSWORD, FakeBotApi, update

pytestmark = pytest.mark.anyio


class FakeApi(FakeBotApi):
    async def send_document(self, chat_id, name, data, mime, caption=None):
        self.calls.append(("sendDocument", chat_id, name, data, mime, caption))


@pytest.fixture
def world(tmp_path):
    runtime = make_runtime(data_dir=tmp_path)
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    api = FakeApi()
    return runtime, owner, api, TelegramBot(runtime, api)


async def pair(bot, runtime, user) -> None:
    code = create_pairing_code(runtime.store, user.id)
    await bot.handle_update(update(f"/pair {code}", message_id=99))


async def test_drop_text_and_files_from_the_chat(world):
    runtime, owner, api, bot = world
    await pair(bot, runtime, owner)
    await bot.handle_update(update("/drop https://example.com/plan", message_id=2))
    [link] = runtime.drop.list(owner.id)
    assert (link.kind, link.text, link.from_label) == (
        "link", "https://example.com/plan", "Telegram",
    )  # fmt: skip
    assert "Saved to your Drop" in api.sent()[-1]

    photo = os.urandom(3000)
    api.files["big-photo"] = photo
    sizes = [{"file_id": "small-photo", "file_size": 100}, {"file_id": "big-photo"}]
    await bot.handle_update(update(None, message_id=3, photo=sizes, caption="/drop@IraBot holiday"))
    item = runtime.drop.list(owner.id)[0]
    assert (item.name, item.mime, item.text) == ("photo.jpg", "image/jpeg", "holiday")
    assert b"".join(runtime.drop.read(item)) == photo

    huge = {"file_id": "huge", "file_name": "film.mp4", "file_size": 30 * 1024 * 1024}
    await bot.handle_update(update(None, message_id=4, document=huge, caption="/drop"))
    assert "20 MB" in api.sent()[-1] and len(runtime.drop.list(owner.id)) == 2
    await bot.handle_update(update("/drop", message_id=5))
    assert "/drop and the text" in api.sent()[-1]


async def test_a_role_without_drop_is_told_so(world):
    runtime, _, api, bot = world
    viewer = runtime.accounts.create_user("viewer@example.com", PASSWORD, "viewer")
    await pair(bot, runtime, viewer)
    await bot.handle_update(update("/drop hello", message_id=2))
    assert "cannot use Drop" in api.sent()[-1] and runtime.drop.list(viewer.id) == []


async def test_new_items_come_to_the_chat_unless_switched_off(world):
    runtime, owner, api, bot = world
    await pair(bot, runtime, owner)
    notify = drop_notifier(runtime, api)
    before = len(api.calls)

    text = runtime.drop.add_text(owner.id, "call the CA", from_label="Mac")
    runtime.drop_notifier = notify  # as the server does when Telegram is on
    await runtime.drop_changed(owner.id, {"type": "drop", "event": "new", "item": text.public()})
    await asyncio.gather(*runtime._drop_forwards)  # sent in the background
    assert api.calls[-1] == ("sendMessage", CHAT, "In your Drop, from Mac:\ncall the CA")
    data = os.urandom(2000)
    file = runtime.drop.add_file(
        owner.id, io.BytesIO(data), "plan.pdf", None, caption="v2", from_label="Pixel 7"
    )
    await notify(owner.id, file.public())
    assert api.calls[-1] == (
        "sendDocument", CHAT, "plan.pdf", data, "application/pdf", "In your Drop, from Pixel 7: v2",
    )  # fmt: skip
    long = runtime.drop.add_text(owner.id, "x" * 5000, from_label="Mac")
    await notify(owner.id, long.public())
    assert api.calls.pop()[2].endswith("x… (the rest is in the Ira app)")
    # What came from Telegram does not go back to it.
    mine = runtime.drop.add_text(owner.id, "from the chat", from_label="Telegram")
    await notify(owner.id, mine.public())
    assert len(api.calls) == before + 2

    with TestClient(create_app(runtime, start_channels=False)) as client:
        body = {"email": "owner@example.com", "password": PASSWORD, "use_cookie": False}
        token = client.post("/v1/auth/login", json=body).json()["session_token"]
        me = {"Authorization": f"Bearer {token}"}
        assert client.get("/v1/me/drop/settings", headers=me).json() == {
            "telegram": True,
            "telegram_ready": True,
        }
        off = client.patch("/v1/me/drop/settings", json={"telegram": False}, headers=me)
        assert off.json()["telegram"] is False
    await notify(owner.id, text.public())
    assert len(api.calls) == before + 2
