"""A stuck tool never holds a conversation or a channel; an action that may or may not have
happened is "unknown", never "running" for ever or "failed"."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from ira.channels.telegram import TelegramBot
from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider
from ira.tools.actions import ActionGuard
from ira.tools.personal import PersonalTool
from ira.tools.registry import ToolRegistry, ToolTimeout

from .conftest import FAST_PIN_ITERATIONS, make_runtime

pytestmark = pytest.mark.anyio

PIN = "4321"


def call(name: str) -> ChatResponse:
    return ChatResponse(text="", tool_calls=[ToolCall("c1", name, json.dumps({}))])


async def test_a_hung_tool_is_given_up_on():
    registry = ToolRegistry()

    @registry.tool
    async def booking_status() -> dict:
        """Ask the booking system."""
        await asyncio.sleep(30)
        return {}

    provider = ScriptedProvider([call("booking_status"), "The booking system is slow."])
    runtime = make_runtime(provider=provider, registry=registry)
    runtime.assistant.tool_seconds = 0.05
    reply = await runtime.assistant.ask("booking?", conversation_id="t")
    assert reply.text == "The booking system is slow."
    assert "did not answer within 0.05 seconds" in provider.calls[1]["messages"][-1].text

    async def hang(arguments: dict[str, Any]) -> Any:
        await asyncio.sleep(30)

    stuck = PersonalTool(
        "mail_search", "Search mail", {"type": "object", "properties": {}}, 0,
        source="connector", label="Mail", run=hang,
    )  # fmt: skip
    provider.script = [call("mail_search"), "Mail is slow."]
    runtime.assistant.personal_tools = lambda uid: [stuck]
    reply = await runtime.assistant.ask("mail?", conversation_id="u", user_id=1)
    assert reply.text == "Mail is slow."


async def test_a_late_or_cut_off_action_is_unknown_not_failed(store, registry, clock, ledger):
    guard = ActionGuard(
        store, registry, pin_iterations=FAST_PIN_ITERATIONS, clock=clock, action_seconds=0.05
    )
    guard.set_pin(PIN)
    tool = registry.get("refund")

    async def slow(pending):
        await asyncio.sleep(30)

    guard.device_runner = slow
    pending = guard.propose(tool, tool.validate({"order_id": "A1", "amount": 5}))
    store.execute("UPDATE pending_actions SET device_id = 7 WHERE id = ?", (pending.id,))
    outcome = await guard.confirm(pending.id, PIN)
    assert outcome.status == "unknown" and "may or may not have happened" in outcome.message
    assert guard.get(pending.id).status == "unknown"

    async def late(pending):
        raise ToolTimeout("the device did not answer within 25 seconds: it may still have done it")

    guard.device_runner = late
    pending = guard.propose(tool, tool.validate({"order_id": "A2", "amount": 5}))
    store.execute("UPDATE pending_actions SET device_id = 7 WHERE id = ?", (pending.id,))
    assert (await guard.confirm(pending.id, PIN)).status == "unknown"

    # Cut off by the server stopping: unknown too, never "executing" for ever.
    guard.device_runner = slow
    pending = guard.propose(tool, tool.validate({"order_id": "A3", "amount": 5}))
    store.execute("UPDATE pending_actions SET device_id = 7 WHERE id = ?", (pending.id,))
    guard.action_seconds = 30
    task = asyncio.ensure_future(guard.confirm(pending.id, PIN))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert guard.get(pending.id).status == "unknown"

    # One left "executing" by a crash is marked unknown when the server starts again.
    stranded = guard.propose(tool, tool.validate({"order_id": "A4", "amount": 5}))
    store.execute("UPDATE pending_actions SET status = 'executing' WHERE id = ?", (stranded.id,))
    assert guard.recover_interrupted() == 1 and guard.get(stranded.id).status == "unknown"
    assert ledger.refunds == []


async def test_one_slow_chat_never_holds_up_another():
    runtime = make_runtime()
    bot = TelegramBot(runtime, api=None)
    done: list[str] = []

    async def handle(update: dict[str, Any]) -> None:
        chat = update["message"]["chat"]["id"]
        text = update["message"]["text"]
        if text == "slow":
            await asyncio.sleep(0.2)
        done.append(f"{chat}:{text}")

    bot.handle_update = handle  # type: ignore[method-assign]

    def update(chat: int, text: str) -> dict[str, Any]:
        return {"message": {"chat": {"id": chat, "type": "private"}, "text": text}}

    bot._dispatch(update(1, "slow"))
    bot._dispatch(update(1, "after"))  # the same chat: waits its turn
    bot._dispatch(update(2, "quick"))  # another chat: not held up
    await asyncio.sleep(0.05)
    assert done == ["2:quick"]
    await asyncio.sleep(0.3)
    assert done == ["2:quick", "1:slow", "1:after"]
