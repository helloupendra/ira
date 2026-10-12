"""The conversation loop: model -> tool calls -> tool results -> answer.

Read tools run immediately. Action tools are turned into pending actions
and the model is told, in the tool result, that nothing has happened yet.
A message that is only a PIN never reaches a model, on any channel.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ira.conversations import Conversations
from ira.models.base import ChatResponse, Message, StreamDone, TextDelta, ToolCall
from ira.models.gateway import Gateway, GatewayError
from ira.security import looks_like_pin
from ira.store import Store
from ira.tools.actions import ActionGuard, PendingAction
from ira.tools.registry import ToolError, ToolRegistry, validation_message

log = logging.getLogger("ira.assistant")

NAME_SETTING = "assistant.name"
MAX_TOOL_RESULT_CHARS = 8000
INVALID_JSON = "arguments were not valid JSON"

SYSTEM_PROMPT = """\
You are {name}, a helpful voice and text assistant for {business}.
Today is {today}.

How you work:
- Use the tools to look things up. Never invent appointments, prices, names or numbers.
- Action tools do not run when you call them. Calling one creates a proposal that the \
owner must confirm with their PIN in a separate step. After proposing, say what you \
proposed and that it needs the PIN. Never say it is done.
- Never ask anyone to tell you the PIN. It is entered on the confirm step, not in chat.
- Your answers may be read aloud: keep them short and plain. Use lists only when they help.
"""


@dataclass
class Reply:
    text: str
    conversation_id: str
    action: PendingAction | None = None
    tools_used: list[str] = field(default_factory=list)
    model: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "conversation_id": self.conversation_id,
            "action": self.action.public() if self.action else None,
            "tools_used": self.tools_used,
            "model": self.model,
        }


class Assistant:
    def __init__(
        self,
        gateway: Gateway,
        registry: ToolRegistry,
        guard: ActionGuard,
        store: Store,
        conversations: Conversations | None = None,
        *,
        name: str = "Ira",
        business: str = "your business",
        instructions: str = "",
        tier: str = "default",
        max_tool_rounds: int = 6,
        history_messages: int = 30,
    ) -> None:
        self.gateway = gateway
        self.registry = registry
        self.guard = guard
        self.store = store
        self.default_name = name
        self.business = business
        self.instructions = instructions.strip()
        self.tier = tier
        self.max_tool_rounds = max_tool_rounds
        self.history_messages = history_messages
        self.conversations = conversations or Conversations(store)
        self._locks: dict[str, asyncio.Lock] = {}

    # Identity.

    @property
    def name(self) -> str:
        return self.store.get_setting(NAME_SETTING) or self.default_name

    def rename(self, new_name: str) -> str:
        cleaned = " ".join(new_name.split())[:32]
        if not cleaned:
            raise ValueError("the name cannot be empty")
        self.store.set_setting(NAME_SETTING, cleaned)
        return cleaned

    def system_prompt(self) -> str:
        today = dt.date.today()
        prompt = SYSTEM_PROMPT.format(
            name=self.name, business=self.business, today=f"{today:%A %d %B %Y} ({today})"
        )
        if self.instructions:
            prompt += "\n" + self.instructions + "\n"
        return prompt

    # Conversations.

    def reset(self, conversation_id: str) -> None:
        self.conversations.reset(conversation_id)

    def history(self, conversation_id: str) -> list[Message]:
        return self.conversations.load(conversation_id, self.history_messages)

    async def ask(
        self,
        text: str,
        *,
        conversation_id: str = "default",
        channel: str = "api",
        actor: str = "owner",
        user_id: int | None = None,
    ) -> Reply:
        reply = Reply(text="", conversation_id=conversation_id)
        parts: list[str] = []
        async for event in self.events(
            text,
            conversation_id=conversation_id,
            channel=channel,
            actor=actor,
            user_id=user_id,
            stream=False,
        ):
            if event["type"] == "delta":
                parts.append(event["text"])
            elif event["type"] == "action":
                reply.action = self.guard.get(event["action"]["id"])
            elif event["type"] == "tool":
                reply.tools_used.append(event["name"])
            elif event["type"] == "done":
                reply.model = event.get("model")
                reply.text = event["text"]
        if not reply.text:
            reply.text = "".join(parts)
        return reply

    async def events(
        self,
        text: str,
        *,
        conversation_id: str = "default",
        channel: str = "api",
        actor: str = "owner",
        user_id: int | None = None,
        stream: bool = True,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run one user turn, yielding events: delta, tool, action, done, error."""
        text = text.strip()
        if looks_like_pin(text):
            # A bare PIN typed into chat: keep it away from every model.
            message = "For safety I never read PINs in chat. Use the confirm step to enter it."
            yield {"type": "delta", "text": message}
            yield {"type": "done", "text": message, "model": None}
            return
        if not text:
            yield {"type": "done", "text": "", "model": None}
            return

        self.conversations.ensure(conversation_id, channel=channel, user_id=user_id)
        lock = self._locks.setdefault(conversation_id, asyncio.Lock())
        async with lock:
            async for event in self._turn(text, conversation_id, channel, actor, stream):
                yield event

    async def _turn(
        self, text: str, conversation_id: str, channel: str, actor: str, stream: bool
    ) -> AsyncIterator[dict[str, Any]]:
        history = self.history(conversation_id)
        start = len(history)
        history.append(Message(role="user", content=text))
        tools = self.registry.schemas() or None
        model: str | None = None
        final_text = ""

        for _ in range(self.max_tool_rounds):
            messages = [Message(role="system", content=self.system_prompt()), *history]
            try:
                response: ChatResponse | None = None
                if stream:
                    async for event in self.gateway.stream(messages, tools, tier=self.tier):
                        if isinstance(event, TextDelta):
                            yield {"type": "delta", "text": event.text}
                        elif isinstance(event, StreamDone):
                            response = event.response
                else:
                    response = await self.gateway.chat(messages, tools, tier=self.tier)
                    if response.text:
                        yield {"type": "delta", "text": response.text}
            except GatewayError as exc:
                log.warning("gateway failed: %s", exc)
                message = (
                    "I can't reach a language model right now "
                    f"({len(exc.errors)} tried). Please try again in a minute."
                )
                history.append(Message(role="assistant", content=message))
                self.conversations.append(conversation_id, history[start:])
                yield {"type": "error", "message": message}
                yield {"type": "done", "text": message, "model": None}
                return
            assert response is not None
            model = response.model

            if not response.tool_calls:
                final_text = response.text
                history.append(Message(role="assistant", content=response.text))
                break

            replayed: list[ToolCall] = []
            results: list[Message] = []
            for call in response.tool_calls:
                yield {"type": "tool", "name": call.name}
                content, safe_call, pending = await self._run_tool(
                    call, conversation_id, channel, actor
                )
                replayed.append(safe_call)
                results.append(
                    Message(role="tool", content=content, tool_call_id=call.id, name=call.name)
                )
                if pending is not None:
                    yield {"type": "action", "action": pending.public()}
            history.append(Message(role="assistant", content=response.text, tool_calls=replayed))
            history.extend(results)
        else:
            final_text = "I could not finish that in the allowed number of steps."
            history.append(Message(role="assistant", content=final_text))
            yield {"type": "delta", "text": final_text}

        self.conversations.append(conversation_id, history[start:])
        yield {"type": "done", "text": final_text, "model": model}

    async def _run_tool(
        self, call: ToolCall, conversation_id: str, channel: str, actor: str
    ) -> tuple[str, ToolCall, PendingAction | None]:
        """Run or propose one tool call. Returns (result text, call to replay, proposal)."""
        arguments = call.parsed_arguments()
        if arguments is None:
            # Replay as {}: providers reject a history holding non-object arguments.
            return _result({"error": INVALID_JSON}), ToolCall(call.id, call.name, "{}"), None
        safe_call = ToolCall(call.id, call.name, call.replay_arguments())

        tool = self.registry.get(call.name)
        if tool is None or not self.registry.is_enabled(call.name):
            return _result({"error": f"unknown tool '{call.name}'"}), safe_call, None
        try:
            args = tool.validate(arguments)
        except ValidationError as exc:
            message = f"invalid arguments: {validation_message(exc)}"
            return _result({"error": message}), safe_call, None

        if tool.kind == "action":
            try:
                pending = self.guard.propose(
                    tool, args, conversation_id=conversation_id, channel=channel, actor=actor
                )
            except ToolError as exc:
                return _result({"error": str(exc)}), safe_call, None
            seconds = round(pending.expires_at - pending.created_at)
            return (
                _result(
                    {
                        "status": "pending_confirmation",
                        "summary": pending.summary,
                        "note": "Nothing has happened yet. The owner must confirm with "
                        f"their PIN within {seconds} seconds.",
                    }
                ),
                safe_call,
                pending,
            )

        try:
            positional, keywords = tool.call_args(args)
            if inspect.iscoroutinefunction(tool.fn):
                value = await tool.fn(*positional, **keywords)
            else:
                value = await asyncio.to_thread(tool.fn, *positional, **keywords)
        except ToolError as exc:
            return _result({"error": str(exc)}), safe_call, None
        except Exception as exc:
            log.exception("tool %s raised", call.name)
            return _result({"error": f"the tool failed ({type(exc).__name__})"}), safe_call, None
        return _result(value), safe_call, None


def _result(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "... (truncated)"
    return text
