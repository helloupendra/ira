"""A conversation goes to the model within a size budget, and one too-long request never
benches a model for everyone."""

from __future__ import annotations

import pytest

from ira.assistant import fit
from ira.models.base import Message, ProviderError, ToolCall
from ira.models.fake import ScriptedProvider
from ira.models.http import classify_status

from .conftest import make_runtime

pytestmark = pytest.mark.anyio


def turn(n: int, result: str) -> list[Message]:
    return [
        Message(role="user", content=f"question {n}"),
        Message(role="assistant", content="", tool_calls=[ToolCall(f"c{n}", "look", "{}")]),
        Message(role="tool", content=result, tool_call_id=f"c{n}", name="look"),
        Message(role="assistant", content=f"answer {n}"),
    ]


def test_old_results_shrink_then_old_turns_go_never_the_new_one():
    history = turn(1, "x" * 20_000) + turn(2, "y" * 20_000) + [Message(role="user", content="now")]
    sent = fit(history, 10_000, current_from=8)
    assert sent[0].role == "user" and sent[-1].content == "now"
    assert all(len(m.content or "") <= 1_520 for m in sent if m.role == "tool")
    assert len(history[2].content) == 20_000  # the stored conversation is untouched

    sent = fit(history, 2_000, current_from=8)
    assert [m.content for m in sent if m.role == "user"] == ["question 2", "now"]

    big_now = history[:8] + turn(3, "z" * 9_000)
    sent = fit(big_now, 4_000, current_from=8, tight=True)
    assert sent[0].content == "question 3"  # this turn alone, its result shortened
    assert len(sent[2].content) <= 4_020


def test_too_long_is_a_request_error_not_an_outage():
    assert (
        classify_status(400, '{"error": "maximum context length is 128000 tokens"}') == "too_long"
    )
    assert classify_status(400, "Input is too long for requested model") == "too_long"
    assert classify_status(400, "invalid tool schema") == "bad_request"
    assert classify_status(503, "overloaded") == "capacity"


async def test_a_too_long_conversation_is_retried_shorter_and_benches_nobody():
    too_long = ProviderError("context length exceeded", kind="too_long", status=400)
    provider = ScriptedProvider([too_long, "Short answer."])
    runtime = make_runtime(provider=provider)
    runtime.conversations.ensure("t", channel="api", user_id=None)
    for n in range(3):
        runtime.conversations.append(
            "t",
            [
                Message(role="user", content=f"q{n}"),
                Message(role="assistant", content="a" * 30_000),
            ],
        )
    reply = await runtime.assistant.ask("aur?", conversation_id="t")
    assert reply.text == "Short answer."
    first, second = (sum(len(m.text or "") for m in c["messages"]) for c in provider.calls)
    assert second < first  # the retry sent much less
    assert runtime.gateway._cool_until == {}  # nobody else loses the model
