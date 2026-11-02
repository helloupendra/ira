"""A live call stays steady (2 Nov 2026: "turant suni fir rukti, beech mai bolna band"):

* a cough, a click or Ira's own voice never cuts her answer short;
* a pause in the middle of a sentence is one turn, not two;
* words from the person do stop her, even after her answer is written and still playing.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from ira.accounts import Principal
from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider
from ira.voice.echo import looks_like_echo, maybe_echo
from ira.voice.live import LiveCall
from ira.voice.providers import FakeTTS

from .conftest import make_runtime

pytestmark = pytest.mark.anyio

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
SHORT = b"\x01\x00" * 3200  # 100 ms of 16 kHz PCM16: a click or a cough
LONG = b"\x01\x00" * 64000  # 2 s of speech


class Utterance:
    """What the speech-to-text gives for one utterance: its partials, then its final text."""

    def __init__(self, heard: dict[str, Any], on_partial: Any) -> None:
        self.partials = heard.get("partials", [])
        self.final = heard.get("final", "")
        self.on_partial = on_partial
        self.fed = False

    def feed(self, pcm: bytes) -> None:
        if not self.fed:
            self.fed = True
            for text in self.partials:
                self.on_partial(text, "en-IN")

    async def finish(self, timeout: float = 5.0) -> tuple[str, str | None]:
        return self.final, "en-IN"

    async def cancel(self) -> None:
        return None


class Speech:
    name = "script"

    def __init__(self, *utterances: dict[str, Any]) -> None:
        self.utterances = list(utterances)

    def live(self, languages: list[str] | None = None, on_partial: Any = None) -> Utterance:
        return Utterance(self.utterances.pop(0), on_partial)


class SlowVoice(FakeTTS):
    """A voice that takes a moment per sentence, so a turn is still going when something happens."""

    def __init__(self, seconds: float = 0.03, fail_first: int = 0) -> None:
        super().__init__()
        self.seconds = seconds
        self.fail_first = fail_first

    async def speak(self, text: str) -> bytes:
        await asyncio.sleep(self.seconds)
        if self.fail_first:
            self.fail_first -= 1
            raise RuntimeError("the voice service hiccuped")
        return await super().speak(text)


class Call:
    def __init__(self, provider: Any, *utterances: dict[str, Any], voice: Any = None) -> None:
        self.provider = provider
        self.runtime = make_runtime(
            provider=provider, stt=Speech(*utterances), tts=voice or FakeTTS()
        )
        self.user = self.runtime.accounts.create_user("owner@example.com", PASSWORD, "owner")
        principal = Principal(self.user, "session", self.user.permissions, "s1")
        self.sent: list[dict[str, Any]] = []
        self.live = LiveCall(
            self.runtime, principal, self._text, self._bytes, conversation_key=lambda c: f"test:{c}"
        )

    async def _text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def _bytes(self, data: bytes) -> None:
        pass

    async def start(self) -> None:
        await self.live.start({"type": "start", "conversation_id": "c1"})

    async def speak(self, audio: bytes = LONG, over: bool | None = None) -> None:
        """The app heard speech, and it ended."""
        await self.begin_speaking(audio, over)
        await self.stop_speaking()

    async def begin_speaking(self, audio: bytes = LONG, over: bool | None = None) -> None:
        start: dict[str, Any] = {"type": "speech_start", "at": 1.0}
        if over is not None:
            start["over"] = over
        await self.live.on_text(json.dumps(start))
        await self.live.on_audio(audio)
        await asyncio.sleep(0)  # partials go out

    async def stop_speaking(self) -> None:
        await self.live.on_text(json.dumps({"type": "speech_end", "at": 2.0}))

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.sent if m["type"] == kind]

    async def until(self, check: Any, seconds: float = 3.0) -> None:
        deadline = asyncio.get_running_loop().time() + seconds
        while not check():
            assert asyncio.get_running_loop().time() < deadline, f"never happened: {self.sent}"
            await asyncio.sleep(0.005)

    async def finished(self, turn: int) -> None:
        await self.until(lambda: any(m["turn"] == turn for m in self.of("done")))

    async def close(self) -> None:
        await self.live.close()


LONG_ANSWER = "Pehla sentence hai. Doosra sentence hai. Teesra sentence hai. Chautha sentence hai."
FOUR = [
    "Pehla sentence hai.",
    "Doosra sentence hai.",
    "Teesra sentence hai.",
    "Chautha sentence hai.",
]


async def test_a_cough_while_ira_thinks_does_not_lose_her_answer():
    call = Call(
        ScriptedProvider([LONG_ANSWER], delay=0.1),
        {"partials": ["kal ka schedule"], "final": "kal ka schedule kya hai"},
        {"partials": [], "final": ""},  # a cough: no words
    )
    await call.start()
    await call.speak()
    await call.speak(SHORT)  # while she thinks
    await call.finished(1)
    assert [m["text"] for m in call.of("audio")] == FOUR
    assert not call.of("interrupted") and not call.of("error")
    assert call.of("speech_ignored")
    await call.close()


async def test_a_cough_between_her_sentences_does_not_cut_her_off():
    call = Call(
        ScriptedProvider([LONG_ANSWER]),
        {"partials": ["kal ka schedule"], "final": "kal ka schedule kya hai"},
        {"partials": [], "final": ""},
        voice=SlowVoice(),
    )
    await call.start()
    await call.speak()
    await call.until(lambda: len(call.of("audio")) == 1)
    await call.speak(SHORT)
    await call.finished(1)
    assert [m["text"] for m in call.of("audio")] == FOUR
    assert not call.of("interrupted") and not call.of("error")
    await call.close()


async def test_a_pause_in_the_middle_of_a_sentence_is_one_turn():
    provider = ScriptedProvider(["Kal aur parso teen meetings hain."], delay=0.2)
    call = Call(
        provider,
        {"partials": ["kal ka"], "final": "kal ka schedule batao"},
        {"partials": ["aur parso"], "final": "aur parso ka bhi"},
    )
    await call.start()
    await call.speak()
    await asyncio.sleep(0.02)  # he took a breath; Ira is still thinking
    await call.speak()
    await call.finished(2)
    heard = call.of("heard")
    assert heard[1]["text"] == "kal ka schedule batao aur parso ka bhi"
    assert heard[1]["replaces"] == 1
    # The half sentence was never answered, and is not in the conversation.
    assert [m["text"] for m in call.of("audio")] == ["Kal aur parso teen meetings hain."]
    said = [m.content for m in call.provider.calls[-1]["messages"] if m.role == "user"]
    assert said == ["kal ka schedule batao aur parso ka bhi"]
    rows = call.runtime.store.query("SELECT role, content FROM messages ORDER BY id")
    assert [r["content"] for r in rows if r["role"] == "user"] == said
    await call.close()


async def test_his_words_stop_her_as_soon_as_they_are_heard():
    call = Call(
        ScriptedProvider([LONG_ANSWER, "Theek hai."]),
        {"partials": ["kal ka schedule"], "final": "kal ka schedule kya hai"},
        {"partials": ["ruko ek minute"], "final": "ruko ek minute"},
        voice=SlowVoice(),
    )
    await call.start()
    await call.speak()
    await call.until(lambda: len(call.of("audio")) == 1)
    await call.begin_speaking()
    await call.until(lambda: bool(call.of("interrupted")))  # before he has finished
    assert call.of("interrupted")[0]["turn"] == 1
    count = len(call.of("audio"))
    await call.stop_speaking()
    await call.finished(2)
    later = [m for m in call.of("audio") if m["turn"] == 1]
    assert len(later) <= count  # nothing of the old answer went out after his words
    assert call.of("heard")[-1]["text"] == "ruko ek minute"
    assert "replaces" not in call.of("heard")[-1]
    await call.close()


async def test_her_own_voice_is_not_taken_for_him():
    call = Call(
        ScriptedProvider([LONG_ANSWER]),
        {"partials": ["kal ka schedule"], "final": "kal ka schedule kya hai"},
        # The microphone heard the speaker: Transcribe writes it in Hindi's script.
        {"partials": ["पहला सेंटेंस"], "final": "पहला सेंटेंस है"},
        voice=SlowVoice(),
    )
    await call.start()
    await call.speak()
    await call.until(lambda: len(call.of("audio")) == 2)
    await call.speak()
    await call.finished(1)
    assert [m["text"] for m in call.of("audio")] == FOUR
    assert not call.of("interrupted")
    assert len(call.of("heard")) == 1  # her echo is not a turn of his
    assert call.of("speech_ignored")
    assert all("पहला" not in m["text"] for m in call.of("partial"))  # nor shown as his
    await call.close()


async def test_a_short_yes_is_his_even_when_she_just_said_the_word():
    call = Call(
        ScriptedProvider(["Kya main call karun? Haan ya na?", "Theek hai."]),
        {"partials": ["usko call karo"], "final": "usko call karo"},
        {"partials": ["haan"], "final": "haan"},
    )
    await call.start()
    await call.speak()
    await call.finished(1)
    await call.speak()
    await call.finished(2)
    assert call.of("heard")[-1]["text"] == "haan"
    assert not call.of("speech_ignored")
    await call.close()


async def test_a_turn_that_used_a_tool_is_never_cancelled_or_merged():
    tool_call = ChatResponse(
        text="", tool_calls=[ToolCall(id="c1", name="nothing_here", arguments="{}")]
    )
    provider = ScriptedProvider([tool_call, "Ho gaya.", "Aur kuch?"], delay=0.05)
    call = Call(
        provider,
        {"partials": ["kuch kaam karo"], "final": "kuch kaam karo abhi"},
        {"partials": ["aur ye bhi"], "final": "aur ye bhi"},
    )
    await call.start()
    await call.speak()
    await call.until(lambda: bool(call.of("tool")))
    await call.speak()
    await call.finished(2)
    assert "replaces" not in call.of("heard")[-1]
    assert call.of("heard")[-1]["text"] == "aur ye bhi"
    done = call.of("done")
    assert [m["turn"] for m in done] == [1, 2] and done[0]["text"] == "Ho gaya."
    await call.close()


async def test_she_can_be_stopped_while_her_finished_answer_still_plays():
    call = Call(
        ScriptedProvider(["Ek lamba jawab tha.", "Theek hai."]),
        {"partials": ["kuch to batao"], "final": "kuch to batao mujhe"},
        {"partials": ["bas karo ab"], "final": "bas karo ab"},
    )
    await call.start()
    await call.speak()
    await call.finished(1)  # written and sent; the phone is still playing it
    await call.begin_speaking()
    await call.until(lambda: bool(call.of("interrupted")))
    assert call.of("interrupted")[0]["turn"] == 1
    await call.stop_speaking()
    await call.finished(2)
    await call.close()


async def test_a_long_try_with_no_words_says_so_but_a_click_does_not():
    call = Call(
        ScriptedProvider([]),
        {"partials": [], "final": ""},
        {"partials": [], "final": ""},
    )
    await call.start()
    await call.speak(SHORT)
    assert call.of("speech_ignored") and not call.of("error")
    await call.speak(LONG)
    assert "catch" in call.of("error")[0]["message"]
    await call.close()


async def test_a_sentence_the_voice_fails_on_is_tried_again():
    call = Call(
        ScriptedProvider(["Ek sentence hai."]),
        {"partials": ["kuch to"], "final": "kuch to batao mujhe"},
        voice=SlowVoice(seconds=0.0, fail_first=1),
    )
    await call.start()
    await call.speak()
    await call.finished(1)
    assert [m["text"] for m in call.of("audio")] == ["Ek sentence hai."]
    await call.close()


async def test_fragments_wait_for_the_rest_instead_of_being_answered_one_by_one():
    provider = ScriptedProvider(["Plot wali news yeh hai."])
    call = Call(
        provider,
        {"partials": ["सेक"], "final": "सेक"},
        {"partials": ["अभी"], "final": "अभी"},
        {"partials": ["plot wali news"], "final": "plot wali news batao"},
    )
    await call.start()
    await call.speak()
    await asyncio.sleep(0.02)
    await call.speak()
    await asyncio.sleep(0.02)
    await call.speak()
    await call.finished(1)
    assert [m["text"] for m in call.of("heard")] == ["सेक अभी plot wali news batao"]
    assert len(provider.calls) == 1
    await call.close()


async def test_a_lone_fragment_is_answered_after_a_short_wait():
    call = Call(ScriptedProvider(["Ji, boliye."]), {"partials": ["ira"], "final": "ira"})
    await call.start()
    await call.speak()
    assert not call.of("heard")  # she waits a moment for the rest
    await call.finished(1)
    assert call.of("heard")[0]["text"] == "ira"
    await call.close()


async def test_a_noise_after_a_fragment_does_not_lose_it():
    call = Call(
        ScriptedProvider(["Ji, boliye."]),
        {"partials": ["ira"], "final": "ira"},
        {"partials": [], "final": ""},
    )
    await call.start()
    await call.speak()
    await call.speak(SHORT)
    await call.finished(1)
    assert call.of("heard")[0]["text"] == "ira"
    await call.close()


async def test_a_reply_in_her_own_words_is_the_persons_when_she_was_quiet():
    # 2 Nov 2026: "mai bolta hu toh sunti nhi": a reply was dropped as her echo for 25 s after.
    call = Call(
        ScriptedProvider(["Pehla sentence hai.", "Theek hai."]),
        {"partials": ["kal ka schedule"], "final": "kal ka schedule kya hai"},
        {"partials": ["pehla sentence hai"], "final": "pehla sentence hai"},
    )
    await call.start()
    await call.speak()
    await call.finished(1)
    await call.speak(over=False)
    await call.finished(2)
    assert [m["text"] for m in call.of("heard")][1] == "pehla sentence hai"
    assert not call.of("speech_ignored")
    await call.close()


def test_a_reply_that_reuses_her_words_is_not_her_echo():
    spoken = ["Aaj admin account mein nuksan hua hai aur ek position khuli hai."]
    assert looks_like_echo("admin account mein nuksan hua", spoken)  # a run, in her order
    assert not looks_like_echo("hua hai aaj", spoken)  # her words, in the person's order
    assert not looks_like_echo("position aaj nuksan account", spoken)
    assert not maybe_echo("nuksan aaj", spoken)


def test_echo_is_told_from_the_person_in_either_script():
    spoken = ["Kal do appointments hain.", "Pehli 10:30 par Avery ke saath hai."]
    assert looks_like_echo("कल दो अपॉइंटमेंट्स हैं", spoken)
    assert looks_like_echo("पहला सेंटेंस है", ["Pehla sentence hai."])
    assert looks_like_echo("kal do appointments hain", spoken)
    assert not looks_like_echo("nahi mujhe parso ka batao", spoken)
    # Too short to tell at the end of a turn: it is his.
    assert not looks_like_echo("haan", ["Haan ya na?"])
    # While he is still speaking, a word she just said waits for more.
    assert maybe_echo("haan", ["Haan ya na?"])
    assert not maybe_echo("ruko", ["Haan ya na?"])
    assert not looks_like_echo("kal do appointments hain", [])
