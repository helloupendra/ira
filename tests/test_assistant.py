"""The conversation loop: tool calls, invalid arguments, proposals, PIN safety, history."""

from __future__ import annotations

import json

import httpx
import pytest

from ira.assistant import INVALID_JSON
from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider
from ira.models.http import HttpClient
from ira.models.openai_compat import OpenAICompatProvider

from .conftest import make_runtime

pytestmark = pytest.mark.anyio


def tool_call(name: str, arguments: str, call_id: str = "c1") -> ChatResponse:
    return ChatResponse(text="", tool_calls=[ToolCall(call_id, name, arguments)])


def sent_messages(provider: ScriptedProvider, call: int):
    return provider.calls[call]["messages"]


async def test_read_tool_result_goes_back_to_the_model(registry):
    provider = ScriptedProvider([tool_call("order_status", '{"order_id": "A1"}'), "It shipped."])
    runtime = make_runtime(provider=provider, registry=registry)

    reply = await runtime.assistant.ask("where is A1?", conversation_id="t")

    assert reply.text == "It shipped."
    assert reply.tools_used == ["order_status"]
    tool_message = sent_messages(provider, 1)[-1]
    assert tool_message.role == "tool"
    assert json.loads(tool_message.text) == {"order_id": "A1", "status": "shipped"}


@pytest.mark.parametrize("bad", ['{"order_id": "A1"', "[1, 2]", '"just a string"', "null"])
async def test_invalid_arguments_are_answered_and_replayed_as_empty_object(registry, bad):
    provider = ScriptedProvider([tool_call("order_status", bad), "Sorry, let me retry."])
    runtime = make_runtime(provider=provider, registry=registry)

    await runtime.assistant.ask("where is A1?", conversation_id="t")

    second_request = sent_messages(provider, 1)
    assistant_turn, tool_result = second_request[-2], second_request[-1]
    assert assistant_turn.tool_calls[0].arguments == "{}"
    assert json.loads(tool_result.text) == {"error": INVALID_JSON}


async def test_invalid_arguments_reach_the_wire_as_empty_object(registry):
    """End to end through the OpenAI-compatible encoder: the bad text never goes back."""
    bodies = []
    replies = iter(
        [
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {"name": "order_status", "arguments": "{oops"},
                                }
                            ]
                        }
                    }
                ]
            },
            {"choices": [{"message": {"content": "done"}}]},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=next(replies))

    http = HttpClient(
        "https://llm.example.com/v1",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    runtime = make_runtime(provider=OpenAICompatProvider(http), registry=registry)

    reply = await runtime.assistant.ask("status?", conversation_id="t")

    assert reply.text == "done"
    replayed = bodies[1]["messages"][-2]["tool_calls"][0]["function"]["arguments"]
    assert replayed == "{}"
    assert "{oops" not in json.dumps(bodies[1])


async def test_validation_errors_are_reported_to_the_model(registry):
    provider = ScriptedProvider([tool_call("order_status", '{"wrong": 1}'), "ok"])
    runtime = make_runtime(provider=provider, registry=registry)
    await runtime.assistant.ask("status?", conversation_id="t")
    result = json.loads(sent_messages(provider, 1)[-1].text)
    assert result["error"].startswith("invalid arguments")


async def test_action_tools_only_propose(registry, ledger):
    provider = ScriptedProvider(
        [
            tool_call("refund", '{"order_id": "A1", "amount": 20}'),
            "Proposed; confirm with your PIN.",
        ]
    )
    runtime = make_runtime(provider=provider, registry=registry)

    reply = await runtime.assistant.ask("refund A1 by 20", conversation_id="t")

    assert reply.action is not None and reply.action.summary == "Refund 20 on order A1"
    assert ledger.refunds == []
    told = json.loads(sent_messages(provider, 1)[-1].text)
    assert told["status"] == "pending_confirmation"
    assert "Nothing has happened yet" in told["note"]


async def test_a_bare_pin_never_reaches_a_model(registry):
    provider = ScriptedProvider(["should not be called"])
    runtime = make_runtime(provider=provider, registry=registry)

    reply = await runtime.assistant.ask("  4321 ", conversation_id="t")

    assert provider.calls == []
    assert "PIN" in reply.text
    assert runtime.conversations.load("t", 10) == []


async def test_history_is_persisted_and_windowed(registry, store):
    provider = ScriptedProvider(
        [tool_call("order_status", '{"order_id": "A1"}'), "Shipped.", "You asked about A1."]
    )
    runtime = make_runtime(provider=provider, registry=registry, store=store)

    await runtime.assistant.ask("where is A1?", conversation_id="t")
    await runtime.assistant.ask("what did I ask?", conversation_id="t")

    roles = [m.role for m in sent_messages(provider, 2)]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "user"]
    # A small window must still start on a user turn, never on a tool result.
    window = runtime.conversations.load("t", 3)
    assert window[0].role == "user"
    transcript = runtime.conversations.transcript("t")
    assert len(transcript) == 6


async def test_model_outage_gives_a_plain_answer(registry):
    from ira.models.base import ProviderError

    provider = ScriptedProvider([ProviderError("down", kind="server")])
    runtime = make_runtime(provider=provider, registry=registry)
    reply = await runtime.assistant.ask("hello", conversation_id="t")
    assert "can't reach a language model" in reply.text


async def test_streamed_events_carry_deltas_actions_and_done(registry):
    provider = ScriptedProvider(
        [tool_call("refund", '{"order_id": "A1", "amount": 5}'), "Please confirm with your PIN."]
    )
    runtime = make_runtime(provider=provider, registry=registry)

    events = [e async for e in runtime.assistant.events("refund", conversation_id="t")]

    kinds = [e["type"] for e in events]
    assert kinds[0] == "tool" and "action" in kinds and kinds[-1] == "done"
    text = "".join(e["text"] for e in events if e["type"] == "delta")
    assert text == "Please confirm with your PIN."


async def test_rename_changes_the_system_prompt(registry):
    provider = ScriptedProvider(["hi"])
    runtime = make_runtime(provider=provider, registry=registry)
    runtime.assistant.rename("  Nova  ")
    await runtime.assistant.ask("hello", conversation_id="t")
    assert runtime.assistant.name == "Nova"
    assert sent_messages(provider, 0)[0].text.startswith("You are Nova")


async def test_tool_events_carry_the_call_and_a_capped_result(registry):
    @registry.tool
    def read_notes(day: str) -> str:
        """Read a day's notes."""
        return "n" * 2000

    calls = ChatResponse(
        text="",
        tool_calls=[
            ToolCall("c1", "read_notes", '{"day": "2026-10-13"}'),
            ToolCall("c1", "order_status", "{oops"),
        ],
    )
    provider = ScriptedProvider([calls, "Here you are."])
    runtime = make_runtime(provider=provider, registry=registry)

    events = [e async for e in runtime.assistant.events("notes?", conversation_id="t")]

    kinds = [e["type"] for e in events if e["type"] in ("tool", "tool_result")]
    assert kinds == ["tool", "tool_result", "tool", "tool_result"]
    tool, result, bad_tool, bad_result = [e for e in events if e["type"].startswith("tool")]
    assert tool == {
        "type": "tool",
        "id": "c1",
        "name": "read_notes",
        "arguments": {"day": "2026-10-13"},
    }
    assert result["id"] == "c1" and result["ok"] is True and result["truncated"] is True
    assert len(result["result"]) == 501 and result["result"].endswith("…")
    # A repeated call id is made unique, and arguments that are not JSON read as {}.
    assert bad_tool["id"] == bad_result["id"] == "c1-2"
    assert bad_tool["arguments"] == {}
    assert bad_result["ok"] is False and bad_result["truncated"] is False
    assert json.loads(bad_result["result"]) == {"error": INVALID_JSON}
    # The model still saw the whole result.
    assert len(sent_messages(provider, 1)[-2].text) == 2000


async def test_the_reply_lists_each_tool_call(registry):
    provider = ScriptedProvider(
        [
            tool_call("order_status", '{"order_id": "A1"}'),
            tool_call("refund", '{"order_id": "A1", "amount": 5}', call_id="c2"),
            "Proposed.",
        ]
    )
    runtime = make_runtime(provider=provider, registry=registry)

    reply = await runtime.assistant.ask("refund A1 if it shipped", conversation_id="t")

    assert reply.tools_used == ["order_status", "refund"]
    status, refund = reply.tool_calls
    assert status["arguments"] == {"order_id": "A1"} and status["ok"] is True
    assert json.loads(status["result"]) == {"order_id": "A1", "status": "shipped"}
    assert refund["id"] == "c2" and refund["ok"] is True
    assert json.loads(refund["result"])["status"] == "pending_confirmation"
