"""A long answer arrives whole: one sentence that looks like a promise, a round that asks it to go
on, or a retry for its letters must not throw it away (seen on a real phone, 5 Nov 2026)."""

from __future__ import annotations

import pytest

from ira.config import ModelsConfig

from .test_read_then_act import READ, World, said, step

pytestmark = pytest.mark.anyio

BODY = " ".join(
    f"{n}. Yeh rajya bahut sundar hai aur yahan ki bhasha alag hai." for n in range(1, 21)
)
HINDI = "आज कैलेंडर में कोई इवेंट नहीं है और कल भी कुछ नहीं है। "


async def test_a_long_answer_with_a_promise_in_it_is_still_the_answer():
    world = World([f"Main abhi likhti hoon. {BODY}"])
    events = await world.turn("Bharat ke rajyon ke naam likho")
    assert len(world.provider.calls) == 1 and world.provider.forced == []
    assert events[-1]["text"] == BODY
    assert "likhti hoon" not in said(events)


async def test_a_short_promise_is_still_pushed_to_act():
    world = World(["Main abhi likhti hoon.", step("screen_read"), "Invoice khula hai."])
    events = await world.turn("mac ki screen padho")
    assert world.ran == ["screen_read"] and events[-1]["text"] == "Invoice khula hai."


async def test_a_go_on_round_that_says_less_does_not_replace_the_answer():
    world = World([READ, BODY, "Bas itna hi."])
    events = await world.turn("screen padho aur batao kya likha hai")
    assert events[-1]["text"] == BODY
    assert "Bas itna hi" not in said(events)  # what it said second never went out either


async def test_a_go_on_round_that_says_more_replaces_the_answer():
    world = World([READ, "Invoice hai.", BODY])
    events = await world.turn("screen padho aur batao kya likha hai")
    assert events[-1]["text"] == BODY


async def test_a_go_on_round_that_runs_a_tool_goes_on_as_before():
    world = World(
        [
            READ,
            BODY,
            step("clipboard_read"),
            "Clipboard mein bhi yahi hai.",
            "Clipboard mein bhi yahi hai.",
        ],
        {"clipboard_read"},
    )
    events = await world.turn("screen padho aur clipboard bhi dekho")
    assert world.ran == ["screen_read", "clipboard_read"]
    assert events[-1]["text"] == "Clipboard mein bhi yahi hai."


async def test_only_the_web_used_and_nothing_left_is_no_reason_to_go_on():
    world = World([step("web_lookup"), BODY])

    async def web_lookup() -> str:
        """Look on the web."""
        return "Results."

    world.runtime.assistant.registry.register(web_lookup, kind="read", name="web_lookup")
    events = await world.turn("Bharat ke rajyon ke naam likho aur unke baare mein batao")
    assert len(world.provider.calls) == 2
    assert events[-1]["text"] == BODY


async def test_a_retry_for_its_letters_that_calls_a_tool_leaves_the_answer():
    world = World([HINDI, step("screen_read")])
    events = await world.turn("aaj mere calendar mein kya hai")
    assert events[-1]["text"].strip() == HINDI.strip()
    assert "samajh nahi" not in said(events)


async def test_a_long_answer_in_the_wrong_letters_is_not_asked_for_again():
    long_hindi = HINDI * 30
    world = World([long_hindi])
    events = await world.turn("aaj mere calendar mein kya hai")
    assert len(world.provider.calls) == 1
    assert events[-1]["text"].strip() == long_hindi.strip()


def test_a_long_answer_has_room_to_finish():
    assert ModelsConfig().max_tokens >= 4096
