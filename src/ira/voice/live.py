"""Real-time voice: one live call, as in docs/realtime.md (protocol 1).

The app sends audio only while the person speaks, and says when they start
and stop. Each utterance is its own Transcribe stream, opened at the first
sound so its setup overlaps with the speech. When they stop, the final text
goes to the same assistant as typing (same conversation, tools, tiers), and
each sentence of the answer is spoken as soon as it is complete. Speech
while Ira talks is a barge-in: the app stops playing at once, and here no
more audio goes out for that turn. The model's answer still finishes and is
kept, so the conversation stays whole; the next turn waits for it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ira.models.base import ProviderError
from ira.voice.shorten import strip_markdown

log = logging.getLogger("ira.voice.live")

PROTOCOL = 1
PING_SECONDS = 20.0
SILENT_SECONDS = 90.0  # nothing from the app for this long: the call is over
FINISH_SECONDS = 4.0  # wait this long for the last words after speech_end
MAX_AUDIO_BYTES = 32_000 * 60  # one utterance: a minute of 16 kHz PCM16
REST_ON_SCREEN = "The rest is on your screen."
SETTLED_SECONDS = 0.3  # a transcript unchanged this long at speech_end is final enough
# Said when Ira must use a tool before it can answer, so the person hears it at once.
ONE_MOMENT = {"en": "One moment.", "hi": "Ek second.", "hinglish": "Ek second."}
# Scripts no one asked for (a model that drifts into Chinese, say) are never spoken.
# Nor is a model's raw tool-call markup that leaked into its text.
_UNSPEAKABLE = re.compile(
    r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]|<\|?tool_call|\bfunctions\.[a-z_]+:\d"
)

_SENTENCE = re.compile(r"(.+?[.!?\u0964\u0965])(?=\s|$)|(.+?[\u3002\uff01\uff1f])|(.+?)\n", re.S)
_CLAUSE = re.compile(r"(.+?[,;:])\s", re.S)


class Sentences:
    """Cuts streaming text into spoken sentences, as soon as each is complete.

    A long clause (over ``clause_after`` characters before any full stop) is
    spoken at its comma, so the first words come sooner.
    """

    def __init__(self, clause_after: int = 90, longest: int = 140) -> None:
        self.buffer = ""
        self.clause_after = clause_after
        self.longest = longest  # past this with no stop or comma, cut at a space

    def feed(self, text: str) -> list[str]:
        self.buffer += text
        out: list[str] = []
        while True:
            match = _SENTENCE.match(self.buffer)
            if match is None and len(self.buffer) > self.clause_after:
                match = _CLAUSE.match(self.buffer)
            if match is not None:
                piece = match.group(0)
            elif len(self.buffer) > self.longest and " " in self.buffer[: self.longest]:
                piece = self.buffer[: self.buffer.rindex(" ", 0, self.longest) + 1]
            else:
                break
            self.buffer = self.buffer[len(piece) :].lstrip()
            spoken = strip_markdown(piece)
            if spoken and re.search(r"\w", spoken):
                out.append(spoken)
        return out

    def flush(self) -> list[str]:
        rest = strip_markdown(self.buffer)
        self.buffer = ""
        return [rest] if rest and re.search(r"\w", rest) else []


@dataclass
class Turn:
    number: int
    text: str
    speech_end_at: float | None  # the app's clock
    started: float  # this server's monotonic clock, when speech_end arrived
    timings: dict[str, int] = field(default_factory=dict)
    interrupted: bool = False
    spoken_chars: int = 0
    seq: int = 0


def languages_for(languages: list[str]) -> list[str]:
    """Transcribe's languages for what a person speaks: Hindi first when they speak it."""
    hindi = bool({"hi", "hinglish"} & set(languages))
    english = "en" in languages or not hindi
    if hindi and english:
        return ["hi-IN", "en-IN"]
    return ["hi-IN"] if hindi else ["en-IN"]


class LiveCall:
    def __init__(
        self,
        runtime: Any,
        principal: Any,
        send_text: Callable[[str], Awaitable[None]],
        send_bytes: Callable[[bytes], Awaitable[None]],
        *,
        conversation_key: Callable[[str], str],
        action_view: Callable[[dict[str, Any]], Any] | None = None,
        max_spoken_chars: int = 600,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.runtime = runtime
        self.principal = principal
        self._send_text = send_text
        self._send_bytes = send_bytes
        self.conversation_key = conversation_key
        self.action_view = action_view
        self.max_spoken_chars = max_spoken_chars
        self.clock = clock
        self.conversation_id = ""
        self.client = ""
        self.turns = 0
        self.transcription: Any = None
        self.audio_bytes = 0
        self.current: Turn | None = None
        self.answer: asyncio.Task[None] | None = None
        self.model_lock = asyncio.Lock()
        self.send_lock = asyncio.Lock()
        self.started_turns: dict[int, Turn] = {}
        self.last_heard = clock()

    # Sending.

    async def send(self, message: dict[str, Any]) -> None:
        async with self.send_lock:
            await self._send_text(json.dumps(message, ensure_ascii=False))

    async def send_audio(self, header: dict[str, Any], audio: bytes) -> None:
        async with self.send_lock:  # the header and its bytes stay together
            await self._send_text(json.dumps(header, ensure_ascii=False))
            await self._send_bytes(audio)

    # The call.

    @property
    def user_id(self) -> int:
        return int(self.principal.user.id)

    def languages(self) -> list[str]:
        return languages_for(self.runtime.assistant.user_settings.get(self.user_id).languages)

    async def start(self, message: dict[str, Any]) -> None:
        client_id = str(message.get("conversation_id") or "")[:64]
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", client_id):
            import secrets

            client_id = secrets.token_hex(6)
        self.conversation_id = client_id
        self.client = str(message.get("client") or "")[:40]
        tts = getattr(self.runtime.tts, "name", None)
        await self.send(
            {
                "type": "ready",
                "protocol": PROTOCOL,
                "conversation_id": client_id,
                "assistant": self.runtime.assistant.name_for(self.user_id),
                "languages": self.languages(),
                "tts": tts,
            }
        )

    def heard_from_app(self) -> None:
        self.last_heard = self.clock()

    async def on_text(self, raw: str) -> bool:
        """One message from the app. Returns False when the call should end."""
        self.heard_from_app()
        try:
            message = json.loads(raw)
        except ValueError:
            await self.send({"type": "error", "message": "messages are JSON", "fatal": False})
            return True
        if not isinstance(message, dict):
            return True
        kind = message.get("type")
        if kind == "speech_start":
            await self.speech_start()
        elif kind == "speech_end":
            await self.speech_end(_number(message.get("at")))
        elif kind == "text":
            text = " ".join(str(message.get("text") or "").split())[:4000]
            if text:
                await self.begin_turn(text, None, None)
        elif kind == "interrupt":
            await self.interrupt()
        elif kind == "played":
            self.played(message)
        elif kind == "bye":
            return False
        return True

    async def on_audio(self, chunk: bytes) -> None:
        self.heard_from_app()
        if self.transcription is None:
            await self.speech_start()  # audio without speech_start: speech started
        self.audio_bytes += len(chunk)
        if self.audio_bytes <= MAX_AUDIO_BYTES:
            self.transcription.feed(chunk)

    async def speech_start(self) -> None:
        await self.interrupt()  # speech while Ira talks: barge-in
        if self.transcription is not None:
            return
        self.audio_bytes = 0
        stt = self.runtime.stt

        def partial(text: str, language: str | None) -> None:
            message = {"type": "partial", "text": text, "language": language}
            asyncio.ensure_future(self.send(message))

        self.transcription = stt.live(self.languages(), partial)

    async def speech_end(self, at: float | None) -> None:
        transcription, self.transcription = self.transcription, None
        if transcription is None:
            return
        started = self.clock()
        settled = getattr(transcription, "updated", None)
        try:
            if (
                settled is not None
                and transcription.text
                and (time.monotonic() - settled >= SETTLED_SECONDS)
            ):
                # Settled while the app waited for quiet: use it now, close in the background.
                text, language = transcription.text, transcription.language
                asyncio.ensure_future(_quietly(transcription.finish(FINISH_SECONDS)))
            else:
                text, language = await transcription.finish(FINISH_SECONDS)
        except ProviderError as exc:
            log.warning("transcription failed: %s", exc)
            await self.send(
                {"type": "error", "message": "I couldn't hear that. Try again?", "fatal": False}
            )
            return
        if not text.strip():
            await self.send(
                {"type": "error", "message": "I didn't catch that. Say it again?", "fatal": False}
            )
            return
        stt_ms = round((self.clock() - started) * 1000)
        await self.begin_turn(text, at, language, started=started, stt_ms=stt_ms)

    async def begin_turn(
        self,
        text: str,
        at: float | None,
        language: str | None,
        *,
        started: float | None = None,
        stt_ms: int | None = None,
    ) -> None:
        self.turns += 1
        turn = Turn(self.turns, text, at, started if started is not None else self.clock())
        if stt_ms is not None:
            turn.timings["stt_ms"] = stt_ms
        self.started_turns[turn.number] = turn
        if len(self.started_turns) > 50:
            self.started_turns.pop(min(self.started_turns))
        await self.send({"type": "heard", "turn": turn.number, "text": text, "language": language})
        self.current = turn
        self.answer = asyncio.ensure_future(self.run_turn(turn))

    async def interrupt(self) -> None:
        turn = self.current
        if turn is None or turn.interrupted:
            return
        turn.interrupted = True
        await self.send({"type": "interrupted", "turn": turn.number})

    def played(self, message: dict[str, Any]) -> None:
        turn = self.started_turns.get(int(_number(message.get("turn")) or 0))
        at = _number(message.get("at"))
        if turn is None or at is None or turn.speech_end_at is None or "latency_ms" in turn.timings:
            return
        latency = at - turn.speech_end_at
        if not 0 <= latency <= 120_000:
            return
        turn.timings["latency_ms"] = round(latency)
        self.runtime.store.execute(
            "INSERT INTO voice_turns (user_id, at, client, latency_ms, stt_ms, model_first_ms, "
            "tts_first_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                self.user_id,
                time.time(),
                self.client,
                turn.timings.get("latency_ms"),
                turn.timings.get("stt_ms"),
                turn.timings.get("model_first_ms"),
                turn.timings.get("tts_first_ms"),
            ),
        )

    # One answer.

    async def run_turn(self, turn: Turn) -> None:
        speech: asyncio.Queue[str | None] = asyncio.Queue()
        speaker = asyncio.ensure_future(self.speak(turn, speech))
        sentences = Sentences()
        message_id = None
        final = ""
        try:
            async with self.model_lock:  # one answer at a time keeps the conversation whole
                async for event in self.runtime.assistant.events(
                    turn.text,
                    conversation_id=self.conversation_key(self.conversation_id),
                    channel="voice",
                    actor=self.principal.actor,
                    user_id=self.user_id,
                ):
                    kind = event.get("type")
                    if kind == "delta":
                        if "model_first_ms" not in turn.timings:
                            turn.timings["model_first_ms"] = self._since(turn)
                        await self.send(
                            {"type": "delta", "turn": turn.number, "text": event["text"]}
                        )
                        for sentence in sentences.feed(event["text"]):
                            self._queue(turn, speech, sentence)
                    elif kind == "tool" and turn.seq == 0 and turn.spoken_chars == 0:
                        from ira.language import detect

                        self._queue(turn, speech, ONE_MOMENT[detect(turn.text)])
                    elif kind == "action":
                        action = event["action"]
                        view = self.action_view(action) if self.action_view else action
                        if hasattr(view, "model_dump"):
                            view = view.model_dump(mode="json")
                        await self.send({"type": "action", "turn": turn.number, "action": view})
                    elif kind == "error":
                        await self.send(
                            {"type": "error", "message": event.get("message"), "fatal": False}
                        )
                    elif kind == "done":
                        final = event.get("text") or ""
                        message_id = event.get("message_id")
            for sentence in sentences.flush():
                self._queue(turn, speech, sentence)
        except Exception:
            log.exception("a live turn failed")
            await self.send(
                {
                    "type": "error",
                    "message": "Something went wrong with that answer.",
                    "fatal": False,
                }
            )
        finally:
            speech.put_nowait(None)
            with contextlib.suppress(Exception):
                await speaker
        await self.send(
            {
                "type": "done",
                "turn": turn.number,
                "text": final,
                "message_id": message_id,
                "interrupted": turn.interrupted,
                "timings": turn.timings,
            }
        )
        if self.current is turn:
            self.current = None

    def _since(self, turn: Turn) -> int:
        return round((self.clock() - turn.started) * 1000)

    def _queue(self, turn: Turn, speech: asyncio.Queue[str | None], sentence: str) -> None:
        if turn.interrupted or turn.spoken_chars >= self.max_spoken_chars:
            return
        if _UNSPEAKABLE.search(sentence):
            log.warning("a sentence in an unexpected script was not spoken")
            return
        turn.spoken_chars += len(sentence)
        speech.put_nowait(sentence)
        if turn.spoken_chars >= self.max_spoken_chars:
            speech.put_nowait(REST_ON_SCREEN)

    async def speak(self, turn: Turn, speech: asyncio.Queue[str | None]) -> None:
        tts = self.runtime.tts
        while True:
            sentence = await speech.get()
            if sentence is None:
                return
            if turn.interrupted or tts is None:
                continue
            synthesis_started = self.clock()
            try:
                audio = await tts.speak(sentence)
            except Exception as exc:  # a failed sentence is skipped, not the call
                log.warning("speech synthesis failed: %s", type(exc).__name__)
                continue
            if "tts_first_ms" not in turn.timings:
                turn.timings["tts_first_ms"] = round((self.clock() - synthesis_started) * 1000)
                turn.timings["first_audio_ms"] = self._since(turn)
            if turn.interrupted:
                continue
            header = {
                "type": "audio",
                "turn": turn.number,
                "seq": turn.seq,
                "text": sentence,
                "format": "mp3",
                "bytes": len(audio),
            }
            turn.seq += 1
            await self.send_audio(header, audio)

    async def close(self) -> None:
        if self.transcription is not None:
            await self.transcription.cancel()
            self.transcription = None
        if self.current is not None:
            self.current.interrupted = True
        if self.answer is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(asyncio.shield(self.answer), 30)


async def _quietly(work: Awaitable[Any]) -> None:
    with contextlib.suppress(Exception):
        await work


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
