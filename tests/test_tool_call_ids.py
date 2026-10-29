"""Tool-call ids in the history are unique and fit for every provider, so a conversation can
fall back from one model to another (Anthropic refuses repeated or odd ids)."""

from __future__ import annotations

import json

import pytest

from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider
from ira.tools.registry import ToolRegistry

from .conftest import make_runtime

pytestmark = pytest.mark.anyio


def call(call_id: str) -> ChatResponse:
    return ChatResponse(text="", tool_calls=[ToolCall(call_id, "booking_status", json.dumps({}))])


async def test_repeated_and_odd_ids_are_made_unique():
    registry = ToolRegistry()

    @registry.tool
    def booking_status() -> dict:
        """Ask the booking system."""
        return {"open": True}

    # A server that names every call the same, and one with characters Anthropic refuses.
    provider = ScriptedProvider(
        [call("call_0"), call("call_0"), "Open.", call("call_0"), call("tool:1.a"), "Still open."]
    )
    runtime = make_runtime(provider=provider, registry=registry)
    await runtime.assistant.ask("open?", conversation_id="t")
    await runtime.assistant.ask("and now?", conversation_id="t")

    history = runtime.assistant.history("t")
    calls = [c.id for m in history for c in m.tool_calls or []]
    assert calls == ["call_0", "call_0-2", "call_0-3", "tool_1_a"]
    results = [m.tool_call_id for m in history if m.role == "tool"]
    assert results == calls  # each result answers its own call
