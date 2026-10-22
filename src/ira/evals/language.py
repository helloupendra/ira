"""``ira eval language``: does Ira understand Hindi, English and Hinglish, and answer in kind?

For each request in ``language.yaml`` it measures:

* **intent**: whether the first tool the model called is the expected one
  (or none, when nothing fits and Ira should answer or ask back);
* **reply language**: whether the answer is in the language of the request
  (Devanagari Hindi, Hinglish in Latin letters, or English);
* with ``--spoken``, **transcription**: each request is spoken by a macOS
  voice, sent to the configured speech-to-text, and scored by word accuracy;
  the transcript is then what Ira is asked.

Devices and search are stand-ins with fixed, fictional answers, so the run
needs only the configured models. It uses a database in memory: nothing is
written to the business folder. Each request costs one or two model calls.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ira.config import Settings
from ira.language import LANGUAGES, detect
from ira.store import Store
from ira.tools.personal import PersonalTool
from ira.tools.registry import ToolError, ToolRegistry
from ira.voice.audio import pcm16_wav

CASES = Path(__file__).resolve().parent / "language.yaml"


def reply_language(text: str) -> str:
    """hi (mostly Devanagari), hinglish (Latin with Hindi words), or en."""
    return detect(text)


def intent_matches(expected: str, tools: list[str]) -> bool:
    """The expected tool anywhere in the turn: listing tabs to find one, then reading it,
    is right. "none" means no tool at all."""
    return expected in tools if expected != "none" else not tools


def words_of(text: str) -> list[str]:
    # The nukta (ख़ or ख) is optional in everyday Hindi spelling: it is not a mishearing.
    text = unicodedata.normalize("NFC", unicodedata.normalize("NFD", text).replace("\u093c", ""))
    cleaned = re.sub(r"[!-/:-@\[-`{-~।॥‘-‟…]", " ", text.lower())
    return cleaned.split()


def devanagari(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum("\u0900" <= c <= "\u097f" for c in letters) > len(letters) / 2


def word_accuracy(expected: str, heard: str) -> float:
    """1 - word error rate, floored at 0: the edit distance over the expected words."""
    a, b = words_of(expected), words_of(heard)
    if not a:
        return 1.0 if not b else 0.0
    previous = list(range(len(b) + 1))
    for i, word in enumerate(a, 1):
        current = [i]
        for j, other in enumerate(b, 1):
            cost = 0 if word == other else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return max(0.0, 1 - previous[-1] / len(a))


@dataclass
class Case:
    id: str
    language: str
    intent: str
    reply: str
    text: str
    # Hinglish as Hindi speech-to-text writes it: in Devanagari ("क्रोम में ..."). The same
    # words in the other script are not a mishearing.
    devanagari: str | None = None


@dataclass
class Result:
    id: str
    language: str
    asked: str
    expected_intent: str
    intent: str
    intent_ok: bool
    expected_reply: str
    reply_language: str
    reply_ok: bool
    reply: str
    seconds: float
    heard: str | None = None
    word_accuracy: float | None = None
    error: str | None = None


@dataclass
class Report:
    model: str
    results: list[Result] = field(default_factory=list)

    def table(self) -> list[dict[str, Any]]:
        rows = []
        for language in (*LANGUAGES, "all"):
            picked = [r for r in self.results if language in ("all", r.language)]
            if not picked:
                continue
            spoken = [r.word_accuracy for r in picked if r.word_accuracy is not None]
            rows.append(
                {
                    "language": language,
                    "requests": len(picked),
                    "intent": sum(r.intent_ok for r in picked) / len(picked),
                    "reply_language": sum(r.reply_ok for r in picked) / len(picked),
                    "transcription": sum(spoken) / len(spoken) if spoken else None,
                }
            )
        return rows


def load_cases(path: Path = CASES) -> list[Case]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Case(**item) for item in data["cases"]]


# Stand-ins for Ira for Mac (its browser and screen tools) and for search: fixed,
# fictional answers.
TABS = {
    "tabs": [
        {"id": "chrome:1:11", "browser": "chrome", "title": "Inbox - Example Mail",
         "url": "https://mail.example.com/"},
        {"id": "chrome:1:12", "browser": "chrome", "title": "Upload - Example Drive",
         "url": "https://drive.example.com/upload", "front": True},
        {"id": "chrome:1:13", "browser": "chrome", "title": "Build #812 - Example CI",
         "url": "https://ci.example.net/builds/812"},
    ],
}  # fmt: skip
# What screen_read shows for whichever tab is in front.
SCREENS = {
    "chrome:1:11": "Inbox (2)\nAsha: Lunch tomorrow?\nExample Shop: Your order has shipped",
    "chrome:1:12": "My Drive > Uploads\nquarterly-report.pdf\n63% uploaded, about 4 min left\n"
    "Cancel",
    "chrome:1:13": "Build #812 - main\nStep 4 of 6: Run tests (2 min 10 s)\nCheckout: done\n"
    "Install: done\nLint: done",
}
NEWS = {
    "items": [
        {
            "title": "Monsoon reaches the coast a week early",
            "site": "news.example.com",
            "date": "2026-10-22",
        }
    ]
}
WEB = {
    "results": [
        {
            "title": "What's new in Python 3.13",
            "site": "docs.example.org",
            "snippet": "A new interactive interpreter and better error messages.",
            "date": "2026-10-01",
        }
    ]
}


def stand_ins() -> list[PersonalTool]:
    def fixed(value: Any):
        async def run(arguments: dict[str, Any]) -> Any:
            return value

        return run

    # Each request starts with the upload tab in front; browser_show_tab changes that, and
    # screen_read shows the tab in front.
    front = {"tab": TABS["tabs"][1]}

    async def show(arguments: dict[str, Any]) -> Any:
        wanted = str(arguments.get("id") or arguments.get("match") or "").lower().strip()
        for tab in TABS["tabs"]:
            words = f"{tab['title']} {tab['url']}".lower()
            if wanted and (wanted == tab["id"] or all(w in words for w in wanted.split())):
                front["tab"] = tab
                return {"summary": f"Switched to {tab['title']} in Chrome.", "tab": tab}
        raise ToolError(f"no open tab matches {wanted!r}")

    async def screen(arguments: dict[str, Any]) -> Any:
        tab = front["tab"]
        return {"app": "Google Chrome", "title": tab["title"], "text": SCREENS[tab["id"]]}

    # Names, tiers and descriptions as Ira for Mac offers them (ToolCatalog.swift).
    browser = {"type": "string", "description": "Only this browser: chrome, safari, arc, ..."}
    mac = {"source": "device", "label": "Studio Mac", "device_id": 1}
    return [
        PersonalTool(
            "browser_tabs",
            "List the tabs open in the browsers on this Mac (Chrome, Safari, Arc, Edge, "
            "Brave): each tab's title and address, which is in front, and an id. Only titles "
            "and addresses, never page contents.",
            {"type": "object", "properties": {"browser": browser}},
            0,
            run=fixed(TABS),
            skill="browser",
            **mac,
        ),
        PersonalTool(
            "browser_show_tab",
            "Bring one browser tab to the front, by words from its title or address or by its "
            "id from browser_tabs. To answer what a tab shows ('how far is that upload?'), "
            "bring it to the front, then use screen_read. Say that you switched to it.",
            {
                "type": "object",
                "properties": {
                    "match": {"type": "string", "description": "Words from its title or address."},
                    "id": {"type": "string", "description": "The tab's id from browser_tabs."},
                    "browser": browser,
                },
            },
            1,
            run=show,
            skill="browser",
            **mac,
        ),
        PersonalTool(
            "screen_read",
            "Read the text of the window in front on this Mac, in any app, only when the "
            "person asks what is on their screen. Returns the app's name, the window's title "
            "and the text.",
            {"type": "object", "properties": {}},
            0,
            run=screen,
            skill="screen",
            **mac,
        ),
        PersonalTool(
            "web_search",
            "Search the web.",
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            0,
            source="web",
            label="web search",
            run=fixed(WEB),
        ),
        PersonalTool(
            "news_search",
            "Search recent news headlines.",
            {"type": "object", "properties": {"query": {"type": "string"}}},
            0,
            source="web",
            label="news feeds",
            run=fixed(NEWS),
        ),
    ]


VOICES = {"hi": "Lekha", "hinglish": "Rishi", "en": "Rishi"}
# Polly's Kajal speaks both; Hinglish in Latin letters reads best as Indian English.
POLLY_LANGUAGES = {"hi": "hi-IN", "hinglish": "en-IN", "en": "en-IN"}


def synthesize_polly(text: str, language: str, region: str, client: Any = None) -> bytes:
    """A request spoken by Amazon Polly (Kajal, neural), as 16 kHz mono WAV."""
    if client is None:
        import botocore.session

        client = botocore.session.get_session().create_client("polly", region_name=region)
    response = client.synthesize_speech(
        Text=text,
        OutputFormat="pcm",
        SampleRate="16000",
        VoiceId="Kajal",
        Engine="neural",
        LanguageCode=POLLY_LANGUAGES.get(language, "en-IN"),
    )
    return pcm16_wav(response["AudioStream"].read(), 16_000)


def synthesize(text: str, language: str, folder: Path) -> bytes:
    """A request spoken by a macOS voice, as 16 kHz mono WAV."""
    if not shutil.which("say") or not shutil.which("afconvert"):
        raise RuntimeError("--spoken needs macOS (say and afconvert)")
    aiff, wav = folder / "speech.aiff", folder / "speech.wav"
    subprocess.run(["say", "-v", VOICES.get(language, "Rishi"), "-o", str(aiff), text], check=True)
    subprocess.run(
        ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff), str(wav)],
        check=True,
    )
    return wav.read_bytes()


async def run(
    settings: Settings, *, spoken: bool = False, only: str | None = None, voice: str | None = None
) -> Report:
    from ira.runtime import build_runtime

    voice = voice or ("say" if shutil.which("say") else "polly")
    tts = settings.voice.tts
    polly_region = tts.region if tts.type == "polly" else "us-east-1"

    store = Store(":memory:")
    runtime = build_runtime(settings, registry=ToolRegistry(), store=store, load_tools=False)
    runtime.assistant.personal_tools = lambda user_id: stand_ins()
    user = runtime.accounts.create_user("eval@example.com", "evaluation-only-password", "staff")
    cases = [c for c in load_cases() if only in (None, c.language)]
    report = Report(model=", ".join(runtime.gateway.tiers.get(runtime.assistant.tier, [])))
    folder = Path(tempfile.mkdtemp(prefix="ira-eval-"))
    try:
        for case in cases:
            heard = accuracy = None
            asked = case.text
            started = time.monotonic()
            error = None
            try:
                if spoken:
                    if runtime.stt is None:
                        raise RuntimeError("voice.stt is not configured")
                    if voice == "polly":
                        speech = await asyncio.to_thread(
                            synthesize_polly, case.text, case.language, polly_region
                        )
                    else:
                        speech = synthesize(case.text, case.language, folder)
                    heard = await runtime.stt.transcribe(speech)
                    accuracy = word_accuracy(case.text, heard)
                    if case.devanagari and devanagari(heard):
                        accuracy = max(accuracy, word_accuracy(case.devanagari, heard))
                    asked = heard
                reply = await runtime.assistant.ask(
                    asked, conversation_id=f"eval:{case.id}", channel="eval", user_id=user.id
                )
                text, tools = reply.text, reply.tools_used
            except Exception as exc:  # a failed case is scored, not fatal
                text, tools, error = "", [], f"{type(exc).__name__}: {exc}"[:300]
            intent = ", ".join(tools) if tools else "none"
            intent_ok = intent_matches(case.intent, tools)
            language = reply_language(text)
            # Ira answers in the script it was asked in: a request heard in Devanagari gets
            # Hindi, which sounds the same when spoken.
            expected = "hi" if heard and devanagari(heard) else case.reply
            report.results.append(
                Result(
                    id=case.id,
                    language=case.language,
                    asked=asked,
                    expected_intent=case.intent,
                    intent=intent,
                    intent_ok=intent_ok,
                    expected_reply=expected,
                    reply_language=language,
                    reply_ok=language == expected,
                    reply=text[:300],
                    seconds=round(time.monotonic() - started, 2),
                    heard=heard,
                    word_accuracy=None if accuracy is None else round(accuracy, 3),
                    error=error,
                )
            )
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        await runtime.aclose()
    return report


def render(report: Report) -> str:
    lines = [f"Language evaluation with {report.model}", ""]
    lines.append(f"{'language':<10} {'requests':>8} {'intent':>8} {'reply':>8} {'heard':>8}")
    for row in report.table():
        heard = "-" if row["transcription"] is None else f"{row['transcription']:.0%}"
        lines.append(
            f"{row['language']:<10} {row['requests']:>8} {row['intent']:>8.0%} "
            f"{row['reply_language']:>8.0%} {heard:>8}"
        )
    misses = [r for r in report.results if not (r.intent_ok and r.reply_ok)]
    if misses:
        lines += ["", "Misses:"]
        for r in misses:
            what = []
            if not r.intent_ok:
                what.append(f"tool {r.intent} (expected {r.expected_intent})")
            if not r.reply_ok:
                what.append(f"replied in {r.reply_language} (expected {r.expected_reply})")
            if r.error:
                what.append(r.error)
            lines.append(f"  {r.id}: {'; '.join(what)}")
    return "\n".join(lines)


def main(
    settings: Settings,
    *,
    spoken: bool,
    only: str | None,
    as_json: bool,
    voice: str | None = None,
) -> int:
    report = asyncio.run(run(settings, spoken=spoken, only=only, voice=voice))
    if as_json:
        data = {"model": report.model, "summary": report.table()}
        data["results"] = [asdict(r) for r in report.results]
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render(report))
    return 0
