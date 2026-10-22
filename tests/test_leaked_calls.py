"""Tool calls a model wrote as text: run as calls when the tool was offered, else left alone."""

from __future__ import annotations

import json

import pytest

from ira.models.base import ChatResponse
from ira.models.fake import ScriptedProvider
from ira.models.leaked import recover

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
