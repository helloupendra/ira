"""Telegram bot over long polling: text and voice notes in, text and voice out.

* A chat must be paired first: ``ira telegram pair`` prints a one-time code,
  and the owner sends ``/pair CODE`` to the bot. Unpaired chats get nothing.
* A bare 4-12 digit message is a PIN. It is deleted from the chat with
  ``deleteMessage`` before anything else happens, used to confirm the chat's
  pending action, and never sent to a model.
* Group chats are ignored: an assistant over private data is a one-to-one thing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
import time
from typing import Any

import httpx

from ira.accounts import Principal
from ira.config import secret
from ira.models.base import ProviderError
from ira.models.http import scrub
from ira.runtime import Runtime
from ira.security import looks_like_pin, sha256_hex, spoken_digits
from ira.store import Store
from ira.voice.audio import AudioError, ogg_to_wav
from ira.voice.shorten import speakable

log = logging.getLogger("ira.telegram")

PAIRING_SECONDS = 600
BOT_INFO_SECONDS = 3600  # how long a getMe answer is kept
BOT_RETRY_SECONDS = 60  # how soon a failed getMe is tried again
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I to misread
MAX_MESSAGE = 4000

HELP = """\
I'm {name}. Ask me anything about {business}, by text or voice note.

When I propose an action, type your PIN to confirm it (I delete the PIN message at once), \
or send /cancel.

/new - start a fresh conversation
/drop <text> - put it in your Drop (or send a file with /drop as its caption)
/cancel - drop the pending action
/name <new name> - rename me (owner or admin)"""


class TelegramError(Exception):
    pass


class TelegramApi:
    """A thin Bot API client. The bot token is part of every URL, so errors are scrubbed."""

    def __init__(
        self,
        token: str,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = "https://api.telegram.org",
    ) -> None:
        self._token = token
        self._client = client or httpx.AsyncClient()
        self._base = base_url.rstrip("/")

    def _scrub(self, text: str) -> str:
        return scrub(text, [self._token])

    async def call(
        self,
        method: str,
        *,
        timeout: float = 30.0,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        **params: Any,
    ) -> Any:
        url = f"{self._base}/bot{self._token}/{method}"
        try:
            if files:
                data = {k: str(v) for k, v in params.items()}
                response = await self._client.post(url, data=data, files=files, timeout=timeout)
            else:
                response = await self._client.post(url, json=params, timeout=timeout)
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramError(self._scrub(f"{method}: {type(exc).__name__}")) from None
        if not body.get("ok"):
            raise TelegramError(self._scrub(f"{method}: {body.get('description', 'failed')}"))
        return body.get("result")

    async def get_updates(self, offset: int | None, timeout: int = 30) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        return await self.call("getUpdates", timeout=timeout + 10, **params) or []

    async def get_me(self) -> dict[str, Any]:
        return await self.call("getMe", timeout=10) or {}

    async def send_message(self, chat_id: int, text: str) -> None:
        await self.call("sendMessage", chat_id=chat_id, text=text)

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        await self.call("deleteMessage", chat_id=chat_id, message_id=message_id)

    async def send_voice(self, chat_id: int, mp3: bytes) -> None:
        await self.call(
            "sendVoice", chat_id=chat_id, files={"voice": ("reply.mp3", mp3, "audio/mpeg")}
        )

    async def send_document(
        self, chat_id: int, name: str, data: bytes, mime: str, caption: str | None = None
    ) -> None:
        params: dict[str, Any] = {"chat_id": chat_id}
        if caption:
            params["caption"] = caption[:1000]
        await self.call(
            "sendDocument", timeout=120, files={"document": (name, data, mime)}, **params
        )

    async def download_file(self, file_id: str) -> bytes:
        info = await self.call("getFile", file_id=file_id)
        path = (info or {}).get("file_path")
        if not path:
            raise TelegramError("getFile returned no path")
        try:
            response = await self._client.get(
                f"{self._base}/file/bot{self._token}/{path}", timeout=60
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TelegramError(self._scrub(f"download: {type(exc).__name__}")) from None
        return response.content

    async def aclose(self) -> None:
        await self._client.aclose()


# --- pairing -----------------------------------------------------------------------


def create_pairing_code(
    store: Store, user_id: int, seconds: float = PAIRING_SECONDS, *, now: float | None = None
) -> str:
    """A one-time code that pairs a chat with this user; only its hash is stored."""
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    now = time.time() if now is None else now
    store.execute(
        "INSERT INTO pairing_codes (code_hash, user_id, created_at, expires_at) "
        "VALUES (?, ?, ?, ?)",
        (sha256_hex(code), user_id, now, now + seconds),
    )
    return code


def chat_name(chat: dict[str, Any]) -> str | None:
    """A private chat's name as Telegram gives it: "Riley Demo (@riley)", or None."""
    full = " ".join(str(chat[k]) for k in ("first_name", "last_name") if chat.get(k)).strip()
    username = chat.get("username")
    if full and username:
        return f"{full} (@{username})"[:100]
    return (full or (f"@{username}" if username else ""))[:100] or None


def redeem_pairing_code(
    store: Store, code: str, chat_id: int, name: str | None = None
) -> int | None:
    """Pair ``chat_id`` with the code's user. Returns the user id, or None."""
    code = code.strip().upper().replace("-", "").replace(" ", "")
    if not code:
        return None
    now = time.time()
    claimed = store.execute(
        "UPDATE pairing_codes SET used_at = ?, chat_id = ? "
        "WHERE code_hash = ? AND used_at IS NULL AND expires_at > ?",
        (now, chat_id, sha256_hex(code), now),
    )
    if claimed.rowcount != 1:
        return None
    row = store.one("SELECT user_id FROM pairing_codes WHERE code_hash = ?", (sha256_hex(code),))
    user_id = int(row["user_id"])
    store.execute(
        "INSERT INTO telegram_chats (chat_id, user_id, paired_at, name) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET "
        "user_id = excluded.user_id, paired_at = excluded.paired_at, name = excluded.name",
        (chat_id, user_id, now, name),
    )
    return user_id


def paired_chats(store: Store) -> list[dict[str, Any]]:
    """Every paired chat with the account it acts as, newest pairing first."""
    rows = store.query(
        "SELECT t.chat_id, t.name, t.paired_at, t.user_id, u.email, u.role "
        "FROM telegram_chats t JOIN users u ON u.id = t.user_id "
        "WHERE u.disabled_at IS NULL ORDER BY t.paired_at DESC, t.chat_id"
    )
    return [dict(r) for r in rows]


def telegram_api(runtime: Runtime) -> Any:
    """The shared Bot API client, made on first use; None while no token is set."""
    if runtime.telegram_api is None:
        token = os.environ.get(runtime.settings.channels.telegram.token_env)
        if not token:
            return None
        runtime.telegram_api = TelegramApi(token)
    return runtime.telegram_api


async def bot_identity(runtime: Runtime) -> dict[str, Any]:
    """The bot's username from getMe, kept for an hour (a failure is retried after a minute).

    Nothing is asked while the token variable is unset.
    """
    cache = runtime.channel_state.setdefault("telegram_bot", {})
    if not os.environ.get(runtime.settings.channels.telegram.token_env):
        return {"username": None, "error": None}
    now = time.time()
    if cache.get("until", 0.0) > now:
        return cache
    api = telegram_api(runtime)
    try:
        me = await api.get_me()
    except TelegramError as exc:  # already scrubbed of the token
        cache.update(error=str(exc), until=now + BOT_RETRY_SECONDS)
        cache.setdefault("username", None)
    else:
        cache.update(username=me.get("username"), error=None, until=now + BOT_INFO_SECONDS)
    return cache


def chat_of(update: dict[str, Any]) -> Any:
    """The chat an update belongs to: a message, an edited one, or a button pressed."""
    for key in ("message", "edited_message"):
        chat = (update.get(key) or {}).get("chat") or {}
        if "id" in chat:
            return chat["id"]
    pressed = ((update.get("callback_query") or {}).get("message") or {}).get("chat") or {}
    return pressed.get("id")


# --- the bot -------------------------------------------------------------------------


class TelegramBot:
    def __init__(self, runtime: Runtime, api: Any, *, poll_timeout: int = 30) -> None:
        self.runtime = runtime
        self.api = api
        self.poll_timeout = poll_timeout
        self.voice_replies = runtime.settings.channels.telegram.voice_replies
        self.state = runtime.channel_state.setdefault(
            "telegram", {"running": False, "last_poll_at": None, "last_error": None, "updates": 0}
        )
        # Each chat's latest update, still being handled: the next waits for it.
        self._chats: dict[Any, asyncio.Future[None]] = {}
        # Update ids handed out (to skip when Telegram sends them again), those still being
        # handled (Telegram is told it has them only once they are done), and the newest.
        self._seen: set[int] = set()
        self._handling: set[int] = set()
        self._newest = 0

    async def run(self) -> None:
        offset: int | None = None
        self.state["running"] = True
        log.info("telegram bot polling")
        try:
            while True:
                try:
                    updates = await self.api.get_updates(offset, self.poll_timeout)
                    self.state["last_poll_at"] = time.time()
                    self.state["last_error"] = None
                except TelegramError as exc:
                    self.state["last_error"] = str(exc)
                    log.warning("telegram poll failed: %s", exc)
                    await asyncio.sleep(5)
                    continue
                fresh = 0
                for update in updates:
                    update_id = int(update["update_id"])
                    self._newest = max(self._newest, update_id)
                    if update_id in self._seen:
                        continue  # handed out already, still being handled
                    fresh += 1
                    self.state["updates"] += 1
                    self._dispatch(update)
                # Telegram forgets an update once a poll asks for the ones after it, so ask
                # only past those already handled: an update being handled when the server
                # restarts comes again, instead of being lost.
                waiting = sorted(self._handling)
                offset = waiting[0] if waiting else (self._newest + 1 if self._newest else None)
                if updates and not fresh:
                    await asyncio.sleep(1)  # only updates still being handled came back
        finally:
            self.state["running"] = False

    def _dispatch(self, update: dict[str, Any]) -> None:
        """Handle an update without holding up other chats: each chat's own updates
        (messages, edits, button presses) stay in order, one after another, while different
        chats are answered side by side (a slow tool or a big voice note in one chat never
        stalls the rest)."""
        chat = chat_of(update)
        update_id = int(update.get("update_id", 0))
        self._seen.add(update_id)
        self._handling.add(update_id)
        if len(self._seen) > 2000:  # those long handled cannot come back
            self._seen = {u for u in self._seen if u >= min(self._handling | {update_id}) - 1000}
        previous = self._chats.get(chat)

        async def run() -> None:
            if previous is not None:
                with contextlib.suppress(BaseException):
                    await previous
            try:
                await self.handle_update(update)
            except Exception:
                log.exception("telegram update %s failed", update.get("update_id"))
            finally:
                self._handling.discard(update_id)

        task = asyncio.ensure_future(run())
        self._chats[chat] = task
        task.add_done_callback(
            lambda done: self._chats.pop(chat, None) if self._chats.get(chat) is done else None
        )

    def _principal(self, chat_id: int) -> Principal | None:
        row = self.runtime.store.one(
            "SELECT user_id FROM telegram_chats WHERE chat_id = ?", (chat_id,)
        )
        if row is None:
            return None
        user = self.runtime.accounts.get_user(int(row["user_id"]))
        if user is None:
            return None
        return Principal(user, "telegram", user.permissions, str(chat_id))

    async def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        if not message or chat.get("type") != "private":
            return
        chat_id = int(chat["id"])
        message_id = int(message.get("message_id", 0))
        text = (message.get("text") or "").strip()

        if text.startswith("/pair"):
            await self._delete(chat_id, message_id)
            user_id = redeem_pairing_code(self.runtime.store, text[5:], chat_id, chat_name(chat))
            await self._send(
                chat_id,
                "Paired. Say hello." if user_id else "That code is not valid or has expired.",
            )
            return

        principal = self._principal(chat_id)
        if principal is None:
            await self._send(
                chat_id, "This assistant is private. Ask the owner for a pairing code."
            )
            return
        name = chat_name(chat)
        if name:  # keep the console's name current; chats paired before it had none
            self.runtime.store.execute(
                "UPDATE telegram_chats SET name = ? WHERE chat_id = ? AND name IS NOT ?",
                (name, chat_id, name),
            )
        conversation_id = f"telegram:{chat_id}"

        if text and looks_like_pin(text):
            # Delete first: the PIN must not sit in the chat history, whatever happens next.
            await self._delete(chat_id, message_id)
            # Its digits only: "4321." or "4 3 2 1" is the PIN, never a wrong one.
            await self._confirm(principal, chat_id, conversation_id, spoken_digits(text) or text)
            return

        command, _, caption = (message.get("caption") or "").strip().partition(" ")
        if command.split("@", 1)[0].lower() == "/drop":
            await self._drop_file(principal, chat_id, message, caption.strip())
            return

        if text.startswith("/"):
            await self._command(principal, chat_id, conversation_id, text)
            return

        heard = False
        voice = message.get("voice") or message.get("audio")
        if voice and not text:
            if not principal.can("voice"):
                await self._send(chat_id, "Your account cannot use voice.")
                return
            transcript = await self._transcribe(chat_id, voice)
            if transcript is None:
                return
            if looks_like_pin(transcript):
                await self._delete(chat_id, message_id)
                await self._send(
                    chat_id, "I deleted that voice note. Please type the PIN instead of saying it."
                )
                return
            text, heard = transcript, True

        if not text:
            return
        if not principal.can("ask"):
            await self._send(chat_id, "Your account cannot ask questions here.")
            return

        reply = await self.runtime.assistant.ask(
            text,
            conversation_id=conversation_id,
            channel="telegram",
            actor=principal.actor,
            user_id=principal.user.id,
            can_approve=principal.can("actions"),
        )
        body = f'Heard: "{text}"\n\n{reply.text}' if heard else reply.text
        await self._send(chat_id, body or "(no answer)")
        if reply.action is not None:
            seconds = max(0, round(reply.action.expires_at - time.time()))
            how = (
                "Reply yes to go ahead, or no."
                if reply.action.tier == 2
                else "Type your PIN to confirm, or /cancel."
            )
            await self._send(
                chat_id,
                f"Proposed: {reply.action.summary}\n{how} It expires in {seconds} seconds.",
            )
        if self.runtime.tts is not None and (
            self.voice_replies == "always" or (self.voice_replies == "voice" and heard)
        ):
            await self._speak(chat_id, reply.text)

    async def _confirm(
        self, principal: Principal, chat_id: int, conversation_id: str, pin: str
    ) -> None:
        if not principal.can("actions"):
            await self._send(chat_id, "Your account cannot confirm actions.")
            return
        pending = self.runtime.guard.latest_pending(conversation_id)
        if pending is None:
            await self._send(chat_id, "No action is waiting for a PIN. It may have expired.")
            return
        outcome = await self.runtime.guard.confirm(
            pending.id,
            pin,
            actor=principal.actor,
            channel="telegram",
            user_id=principal.user.id,
            role=principal.user.role,
        )
        await self._send(chat_id, outcome.message)
        after = await self.runtime.continue_after(outcome, actor=principal.actor)
        if after and after.get("text"):
            await self._send(chat_id, after["text"])  # Ira saw the result and carried on

    async def _command(
        self, principal: Principal, chat_id: int, conversation_id: str, text: str
    ) -> None:
        command, _, argument = text.partition(" ")
        command = command.split("@", 1)[0].lower()
        assistant = self.runtime.assistant
        if command in ("/start", "/help"):
            await self._send(chat_id, HELP.format(name=assistant.name, business=assistant.business))
        elif command == "/new":
            assistant.reset(conversation_id)
            await self._send(chat_id, "Fresh start. What can I do for you?")
        elif command == "/drop":
            await self._drop_text(principal, chat_id, argument)
        elif command == "/cancel":
            pending = self.runtime.guard.latest_pending(conversation_id)
            if pending is None:
                await self._send(chat_id, "Nothing is waiting to be cancelled.")
            else:
                outcome = self.runtime.guard.cancel(
                    pending.id, actor=principal.actor, channel="telegram", user_id=principal.user.id
                )
                await self._send(chat_id, outcome.message)
        elif command == "/name":
            if not argument.strip():
                await self._send(chat_id, f"My name is {assistant.name}.")
            elif not principal.can("admin.write"):
                await self._send(chat_id, "Only an owner or admin can rename me.")
            else:
                name = assistant.rename(argument)
                await self._send(chat_id, f"Done. Call me {name}.")
        else:
            await self._send(chat_id, "I don't know that command. Send /help.")

    # Drop: "/drop some text", or a file sent with "/drop" as its caption.

    async def _drop_text(self, principal: Principal, chat_id: int, text: str) -> None:
        from ira.drop import DropError

        if not principal.can("drop"):
            await self._send(chat_id, "Your account cannot use Drop.")
            return
        if not text.strip():
            await self._send(
                chat_id, "Send /drop and the text, or a file with /drop as its caption."
            )
            return
        try:
            item = self.runtime.drop.add_text(principal.user.id, text, from_label="Telegram")
        except DropError as exc:
            await self._send(chat_id, f"Not saved: {exc}")
            return
        frame = {"type": "drop", "event": "new", "item": item.public()}
        await self.runtime.drop_changed(principal.user.id, frame)
        await self._send(chat_id, "Saved to your Drop: it is on your devices now.")

    async def _drop_file(
        self, principal: Principal, chat_id: int, message: dict[str, Any], caption: str
    ) -> None:
        import io

        from ira.drop import DropError

        photos = message.get("photo") or []
        photo = photos[-1] if photos else None  # the largest size Telegram made
        found = (
            message.get("document")
            or message.get("video")
            or message.get("audio")
            or message.get("voice")
            or photo
        )
        if not found or not principal.can("drop"):
            await self._drop_text(principal, chat_id, caption)
            return
        size = int(found.get("file_size") or 0)
        if size > TELEGRAM_DOWNLOAD_LIMIT:
            await self._send(
                chat_id,
                "Telegram lets bots fetch files up to 20 MB: send this one from the Ira app.",
            )
            return
        if found is photo:
            name, mime = "photo.jpg", "image/jpeg"  # Telegram sends photos as JPEG
        else:
            name, mime = found.get("file_name") or "file", found.get("mime_type")
        try:
            data = await self.api.download_file(found["file_id"])
            item = await asyncio.to_thread(
                self.runtime.drop.add_file,
                principal.user.id,
                io.BytesIO(data),
                name,
                mime,
                caption=caption or None,
                from_label="Telegram",
            )
        except (TelegramError, DropError) as exc:
            await self._send(chat_id, f"Not saved: {exc}")
            return
        frame = {"type": "drop", "event": "new", "item": item.public()}
        await self.runtime.drop_changed(principal.user.id, frame)
        await self._send(chat_id, f"Saved {item.name} to your Drop: it is on your devices now.")

    async def _transcribe(self, chat_id: int, voice: dict[str, Any]) -> str | None:
        stt = self.runtime.stt
        if stt is None:
            await self._send(chat_id, "Voice notes are not set up here. Please type instead.")
            return None
        if int(voice.get("duration") or 0) > self.runtime.settings.voice.max_audio_seconds:
            await self._send(chat_id, "That voice note is too long for me.")
            return None
        try:
            ogg = await self.api.download_file(voice["file_id"])
            wav = await asyncio.to_thread(ogg_to_wav, ogg)
            transcript = (await stt.transcribe(wav)).strip()
        except AudioError as exc:
            await self._send(chat_id, f"I couldn't read that voice note: {exc}")
            return None
        except (TelegramError, ProviderError) as exc:
            log.warning("voice note failed: %s", exc)
            await self._send(chat_id, "I couldn't transcribe that voice note. Please try again.")
            return None
        if not transcript:
            await self._send(chat_id, "I didn't catch any words in that voice note.")
            return None
        return transcript

    async def _speak(self, chat_id: int, text: str) -> None:
        spoken = speakable(text, self.runtime.settings.voice.max_spoken_chars)
        if not spoken or self.runtime.tts is None:
            return
        try:
            audio = await self.runtime.tts.speak(spoken)
            await self.api.send_voice(chat_id, audio)
        except (ProviderError, TelegramError) as exc:
            log.warning("voice reply failed: %s", exc)

    async def _send(self, chat_id: int, text: str) -> None:
        for start in range(0, max(len(text), 1), MAX_MESSAGE):
            try:
                await self.api.send_message(chat_id, text[start : start + MAX_MESSAGE])
            except TelegramError as exc:
                log.warning("send failed: %s", exc)
                return

    async def _delete(self, chat_id: int, message_id: int) -> None:
        try:
            await self.api.delete_message(chat_id, message_id)
        except TelegramError as exc:
            # Telegram refuses deletes after 48 hours or without rights; say so in the log.
            log.warning("could not delete message %s: %s", message_id, exc)


def event_message(event: dict[str, Any]) -> str:
    """A device's event as one chat message: its title (and device), then its text."""
    head = event.get("title") or "Ira"
    if event.get("device"):
        head = f"{head} ({event['device']})"
    text = (event.get("text") or "").strip()
    return f"{head}\n{text}" if text and text != event.get("title") else head


TELEGRAM_DOWNLOAD_LIMIT = 20 * 1024 * 1024  # what a bot may fetch from Telegram
TELEGRAM_SEND_LIMIT = 45 * 1024 * 1024  # what a bot may send (50 MB), with room to spare
TELEGRAM_TEXT_LIMIT = 3500  # a message holds 4,096 characters


def drop_notifier(runtime: Runtime, api: Any = None) -> Any:
    """Forward a new Drop item to the person's own paired chats: text as a message, a file
    as a document (up to Telegram's limit). Not one that came from Telegram, and not when
    the server or the person switched it off."""

    async def notify(user_id: int, item: dict[str, Any]) -> None:
        if item.get("from_label") == "Telegram" or not runtime.settings.drop.telegram_forward:
            return
        if not runtime.assistant.user_settings.get(user_id).drop_telegram:
            return
        client = api or telegram_api(runtime)
        if client is None:
            return
        rows = runtime.store.query(
            "SELECT t.chat_id FROM telegram_chats t JOIN users u ON u.id = t.user_id "
            "WHERE t.user_id = ? AND u.disabled_at IS NULL",
            (user_id,),
        )
        if not rows:
            return
        head = f"In your Drop, from {item.get('from_label') or 'a device'}:"
        data = None
        if item.get("kind") == "file" and (item.get("size") or 0) <= TELEGRAM_SEND_LIMIT:
            stored = runtime.drop.get(user_id, int(item["id"]))
            if stored is not None:
                data = await asyncio.to_thread(lambda: b"".join(runtime.drop.read(stored)))
        for row in rows:
            chat_id = int(row["chat_id"])
            try:
                if item.get("kind") != "file":
                    text = item.get("text") or ""
                    if len(text) > TELEGRAM_TEXT_LIMIT:
                        text = text[:TELEGRAM_TEXT_LIMIT] + "… (the rest is in the Ira app)"
                    await client.send_message(chat_id, f"{head}\n{text}")
                elif data is not None:
                    caption = f"{head} {item.get('text') or ''}".strip()
                    await client.send_document(
                        chat_id, item.get("name") or "file", data, item.get("mime") or
                        "application/octet-stream", caption,
                    )  # fmt: skip
                else:
                    megabytes = round((item.get("size") or 0) / 1024 / 1024)
                    await client.send_message(
                        chat_id,
                        f"{head} {item.get('name')} ({megabytes} MB), too big for Telegram: "
                        "open it in the Ira app.",
                    )
            except TelegramError as exc:
                log.warning("forwarding a Drop item to Telegram failed: %s", exc)

    return notify


def event_notifier(runtime: Runtime, api: Any = None) -> Any:
    """Send a person's device events to their own paired chats, and nobody else's.

    Text always; voice too when text-to-speech is set up and voice replies are not off.
    """

    async def notify(user_id: int, event: dict[str, Any]) -> None:
        client = api or telegram_api(runtime)
        if client is None:
            return
        rows = runtime.store.query(
            "SELECT t.chat_id FROM telegram_chats t JOIN users u ON u.id = t.user_id "
            "WHERE t.user_id = ? AND u.disabled_at IS NULL",
            (user_id,),
        )
        if not rows:
            return
        text = event_message(event)
        audio = None
        if runtime.tts is not None and runtime.settings.channels.telegram.voice_replies != "off":
            spoken = speakable(text, runtime.settings.voice.max_spoken_chars)
            try:
                audio = await runtime.tts.speak(spoken) if spoken else None
            except ProviderError as exc:
                log.warning("voice for an event failed: %s", exc)
        for row in rows:
            chat_id = int(row["chat_id"])
            try:
                await client.send_message(chat_id, text[:MAX_MESSAGE])
                if audio:
                    await client.send_voice(chat_id, audio)
            except TelegramError as exc:
                log.warning("sending an event failed: %s", exc)

    return notify


def start_telegram(runtime: Runtime) -> asyncio.Task:
    cfg = runtime.settings.channels.telegram
    secret(cfg.token_env, purpose="the Telegram channel")  # fails, naming the variable, if unset
    bot = TelegramBot(runtime, telegram_api(runtime))
    return asyncio.create_task(bot.run(), name="ira-telegram")
