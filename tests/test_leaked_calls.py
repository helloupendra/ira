"""Tool calls a model wrote as text: run as calls when the tool was offered, else left alone."""

from __future__ import annotations

import json

import pytest

from ira.models.base import ChatResponse
from ira.models.fake import ScriptedProvider
from ira.models.leaked import MarkupGate, before_markup, recover

from .conftest import make_runtime

pytestmark = pytest.mark.anyio

OFFERED = {"screen_read", "order_status"}


def test_the_three_ways_models_write_a_call():
    prose, calls = recover(
        '<invoke name="screen_read">\n<parameter name="input">{}</parameter>\n</invoke>', OFFERED
    )
    assert prose == "" and [(c.name, c.parsed_arguments()) for c in calls] == [("screen_read", {})]

    text = (
        'Dekhti hoon. <function_calls><invoke name="order_status">'
        '<parameter name="order_id">A1</parameter></invoke></function_calls>'
    )
    prose, calls = recover(text, OFFERED)
    assert prose == "Dekhti hoon." and calls[0].parsed_arguments() == {"order_id": "A1"}

    kimi = (
        "<|tool_calls_section_begin|> <|tool_call_begin|> functions.order_status:0 "
        '<|tool_call_argument_begin|> {"order_id": "B2"} <|tool_call_end|> '
        "<|tool_calls_section_end|>"
    )
    prose, calls = recover(kimi, OFFERED)
    assert (
        prose == ""
        and calls[0].name == "order_status"
        and json.loads(calls[0].arguments) == {"order_id": "B2"}
    )

    bare = 'screen_read:0 <|tool_call_argument_begin|> {"": {}} <|tool_call_end|>'
    prose, calls = recover(bare, OFFERED)  # seen without "functions.", and with {"": {}}
    assert prose == "" and [(c.name, c.parsed_arguments()) for c in calls] == [("screen_read", {})]

    hermes = '<tool_call>{"name": "order_status", "arguments": {"order_id": "C3"}}</tool_call>'
    assert recover(hermes, OFFERED)[1][0].parsed_arguments() == {"order_id": "C3"}

    two = (
        '<invoke name="screen_read"></invoke><invoke name="order_status">'
        '<parameter name="order_id">D4</parameter></invoke>'
    )
    calls = recover(two, OFFERED)[1]
    assert [c.name for c in calls] == ["screen_read", "order_status"] and calls[0].id != calls[1].id


def test_text_that_is_not_an_offered_call_stays_text():
    for text in (
        "Use <invoke> tags like this.",
        '<invoke name="delete_everything"></invoke>',  # not offered: never run
        '<tool_call>{"name": "order_status", "arguments": [1]}</tool_call>',  # not an object
        '<invoke name="screen_read"></invoke> and <invoke name="rm_rf"></invoke>',
    ):
        assert recover(text, OFFERED) == (text, [])


async def test_a_call_written_as_text_runs(registry):
    leaked = ChatResponse(
        text='<invoke name="order_status"><parameter name="order_id">A1</parameter></invoke>'
    )
    provider = ScriptedProvider([leaked, "It shipped."])
    runtime = make_runtime(provider=provider, registry=registry)

    reply = await runtime.assistant.ask("where is A1?", conversation_id="t")

    assert reply.text == "It shipped." and reply.tools_used == ["order_status"]
    assert provider.calls[1]["messages"][-1].role == "tool"


def test_the_name_as_a_tag_as_on_the_live_call_of_31_october():
    offered = OFFERED | {"trading_desk"}
    seen = '<tool_call>\n<trading_desk>\n{"question": "आज market खुला है या बंद?"}\n</tool_call>'
    prose, calls = recover(seen, offered)
    assert prose == "" and [(c.name, c.parsed_arguments()) for c in calls] == [
        ("trading_desk", {"question": "आज market खुला है या बंद?"})
    ]
    closed = '<tool_call><order_status>{"order_id": "E5"}</order_status></tool_call>'
    assert recover(closed, OFFERED)[1][0].parsed_arguments() == {"order_id": "E5"}


def test_the_name_bare_with_json_or_glms_key_and_value_pairs():
    named = 'Dekhti hoon. <tool_call>order_status {"order_id": "F6"}</tool_call>'
    prose, calls = recover(named, OFFERED)
    assert prose == "Dekhti hoon." and calls[0].parsed_arguments() == {"order_id": "F6"}

    glm = (
        "<tool_call>order_status\n<arg_key>order_id</arg_key>\n<arg_value>G7</arg_value>\n"
        "</tool_call>"
    )
    assert recover(glm, OFFERED)[1][0].parsed_arguments() == {"order_id": "G7"}
    bare = "<tool_call>screen_read</tool_call>"
    assert [(c.name, c.parsed_arguments()) for c in recover(bare, OFFERED)[1]] == [
        ("screen_read", {})
    ]


def test_a_tagged_call_to_a_tool_not_offered_stays_text():
    text = "<tool_call><trading_desk>{}</trading_desk></tool_call>"
    assert recover(text, OFFERED) == (text, [])


def test_the_prose_before_markup_that_cannot_run():
    assert before_markup("Main dekhti hoon:\n<tool_call><x>{}</tool_call>") == "Main dekhti hoon:"
    assert before_markup("Padh rahi hoon.\n\n<｜DSML｜function_calls>") == "Padh rahi hoon."
    assert before_markup("Use <invoke> tags like this, and 2 < 3.") is None
    assert before_markup("NIFTY < 24,000 today.") is None


def test_the_gate_holds_back_what_may_be_markup_and_lets_text_through():
    def run(*pieces: str) -> str:
        gate = MarkupGate()
        return "".join(gate.feed(p) for p in pieces) + gate.flush()

    assert run("NIFTY ", "< 24,", "000.") == "NIFTY < 24,000."
    assert run("Use <b>bold", "</b>.") == "Use <b>bold</b>."
    assert run("ends with <") == "ends with <"
    assert run("Dekhti hoon. <tool", "_call>\n<trading_desk>", '{"q": 1}</tool_call>') == (
        "Dekhti hoon. "
    )
    assert run("<inv", 'oke name="screen_read"></invoke>') == ""
    assert run("<inv", "oked>") == "<invoked>"

    gate = MarkupGate()
    assert gate.feed("a <") == "a " and gate.feed(" 5 lakh") == "< 5 lakh" and not gate.cut


async def test_a_tagged_call_runs_and_its_markup_never_streams(registry):
    leaked = ChatResponse(text='<tool_call>\n<order_status>\n{"order_id": "A1"}\n</tool_call>')
    provider = ScriptedProvider([leaked, "It shipped."])
    runtime = make_runtime(provider=provider, registry=registry)

    events = [
        e async for e in runtime.assistant.events("where is A1?", conversation_id="t", stream=True)
    ]

    shown = "".join(e["text"] for e in events if e["type"] == "delta")
    assert shown == "It shipped." and events[-1]["text"] == "It shipped."
    assert provider.calls[1]["messages"][-1].role == "tool"


async def test_markup_that_cannot_run_is_asked_for_once_more(registry):
    leaked = ChatResponse(text="Dekhti hoon. <tool_call><delete_everything>{}</tool_call>")
    provider = ScriptedProvider([leaked, "A1 shipped kal."])
    runtime = make_runtime(provider=provider, registry=registry)

    events = [e async for e in runtime.assistant.events("A1?", conversation_id="t", stream=True)]

    shown = "".join(e["text"] for e in events if e["type"] == "delta")
    assert "<" not in shown and shown.endswith("A1 shipped kal.")
    assert events[-1]["text"] == "A1 shipped kal."
    assert "does not run" in provider.calls[1]["messages"][0].text
    assert runtime.assistant.history("t")[-1].text == "A1 shipped kal."


async def test_markup_twice_ends_in_asking_the_person_again(registry):
    leaked = "<tool_call><delete_everything>{}</tool_call>"
    provider = ScriptedProvider([ChatResponse(text=leaked), ChatResponse(text=leaked)])
    runtime = make_runtime(provider=provider, registry=registry)

    reply = await runtime.assistant.ask("where is my order?", conversation_id="t")

    assert reply.text == "Sorry, I didn't get that. Could you say it again?"
    assert len(provider.calls) == 2
