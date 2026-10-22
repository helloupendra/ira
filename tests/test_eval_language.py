"""The language evaluation: its set, its scoring, and a run with the demo router."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ira.config import Settings
from ira.evals.language import (
    LANGUAGES,
    load_cases,
    render,
    reply_language,
    run,
    stand_ins,
    word_accuracy,
)


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
