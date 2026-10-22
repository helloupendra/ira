"""The language evaluation: its set, its scoring, and a run with the demo router."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pytest

from ira.config import Settings
from ira.evals.language import (
    LANGUAGES,
    intent_matches,
    load_cases,
    render,
    reply_language,
    run,
    stand_ins,
    synthesize_polly,
    word_accuracy,
)
from ira.voice.audio import wav_info


def test_the_set_is_valid_and_covers_three_languages():
    cases = load_cases()
    intents = {tool.name for tool in stand_ins()} | {"none"}
    assert len({c.id for c in cases}) == len(cases)
    assert {c.language for c in cases} == set(LANGUAGES)
    for case in cases:
        assert case.intent in intents, case.id
        assert case.reply in LANGUAGES, case.id
        if case.language == "hi":
            assert reply_language(case.text) == "hi", case.id


def test_reply_language():
    assert reply_language("अपलोड 63% हुआ है, लगभग 4 मिनट बाकी।") == "hi"
    assert reply_language("Upload 63% ho gaya hai, abhi 4 minute baaki hain.") == "hinglish"
    assert reply_language("The upload is at 63%, about 4 minutes left.") == "en"
    assert reply_language("Open the main tab in the browser.") == "en"  # main, tab: English too


def test_quoted_data_does_not_change_the_language():
    # Real replies from the first run on Bedrock: Hindi prose around English titles.
    tabs = (
        "आपके Chrome में 3 टैब खुले हैं:\n1. **Inbox - Example Mail** (mail.example.com)\n"
        "2. **Upload - Example Drive** (drive.example.com/upload)"
    )
    assert reply_language(tabs) == "hi"
    web = (
        "Python 3.13 के बारे में यह जानकारी मिली (docs.example.org, 1 Oct 2026): - नया "
        "interactive interpreter - बेहतर error messages क्या आप और details चाहते हैं?"
    )
    assert reply_language(web) == "hi"
    assert reply_language('Main ab "Upload - Example Drive" tab pe nazar rakh raha hoon.') == (
        "hinglish"
    )
    assert reply_language("**Monsoon reaches the coast a week early**") == "en"  # only data
    # A real miss stays a miss: an English opening on a Hindi question.
    said = "You're welcome! मैं आपकी मदद के लिए yahan hoon. Agar kuch bhi chahiye ho to batayein."
    assert reply_language(said) == "hinglish"


def test_the_expected_tool_may_come_after_another():
    assert intent_matches("screen_read", ["browser_show_tab", "screen_read"])
    assert not intent_matches("screen_read", ["browser_tabs", "browser_show_tab"])
    assert intent_matches("none", []) and not intent_matches("none", ["web_search"])


def test_word_accuracy():
    assert word_accuracy("kal subah 9 baje yaad dilana", "Kal subah 9 baje yaad dilana.") == 1.0
    assert word_accuracy("kal subah 9 baje yaad dilana", "kal subha 9 baje yaad dilana") == 5 / 6
    assert word_accuracy("आज की ख़बर", "आज की ख़बर।") == 1.0
    assert word_accuracy("a b", "x y z w") == 0.0


def test_a_run_with_the_demo_router_scores_every_case(tmp_path: Path):
    report = asyncio.run(run(Settings(data_dir=tmp_path)))
    assert len(report.results) == len(load_cases())
    assert report.model == "demo:router"
    rows = {row["language"]: row for row in report.table()}
    assert rows["all"]["requests"] == len(load_cases())
    # The keyword router knows the Hinglish quick-start phrases.
    assert rows["hinglish"]["intent"] >= 0.9
    assert "Misses:" in render(report)
    assert not (tmp_path / "ira.db").exists()  # the run keeps nothing


def test_polly_can_speak_the_requests():
    botocore = pytest.importorskip("botocore.session")
    from botocore.response import StreamingBody
    from botocore.stub import Stubber

    client = botocore.get_session().create_client(
        "polly",
        region_name="ap-south-1",
        aws_access_key_id="AKIDEXAMPLE",
        aws_secret_access_key="secret-for-tests",  # pragma: allowlist secret
    )
    pcm = b"\x01\x00" * 1600
    with Stubber(client) as stub:
        stub.add_response(
            "synthesize_speech",
            {"AudioStream": StreamingBody(io.BytesIO(pcm), len(pcm)), "ContentType": "audio/pcm"},
            {
                "Text": "आज की ख़बर",
                "OutputFormat": "pcm",
                "SampleRate": "16000",
                "VoiceId": "Kajal",
                "Engine": "neural",
                "LanguageCode": "hi-IN",
            },
        )
        wav = synthesize_polly("आज की ख़बर", "hi", "ap-south-1", client)
    assert wav_info(wav).sample_rate == 16_000 and wav_info(wav).frames == 1600
