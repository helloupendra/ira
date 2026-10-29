"""OpenAI-compatible chat completions with tools and streaming.

One implementation covers OpenAI itself, Amazon Bedrock's Mantle endpoint,
local servers (llama.cpp, vLLM, Ollama) and the many hosted services that
speak the same protocol.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from ira.models.base import (
    ChatResponse,
    Message,
    ProviderError,
    StreamDone,
    StreamEvent,
    TextDelta,
    ToolCall,
    Usage,
    openai_usage,
)
from ira.models.http import HttpClient, sse_data


def to_openai_message(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id or "",
            "content": message.text,
        }
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.text or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.replay_arguments()},
                }
                for call in message.tool_calls
            ],
        }
    content = message.content if message.content is not None else ""
    return {"role": message.role, "content": content}


def to_openai_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec.get("description", ""),
                "parameters": spec.get("parameters") or {"type": "object", "properties": {}},
            },
        }
        for spec in tools
    ]


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # some servers return content parts
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def _arguments_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value)  # a few servers send a parsed object


def parse_completion(data: dict[str, Any], model: str) -> ChatResponse:
    if data.get("error"):
        raise ProviderError(f"provider error: {data['error']}", kind="server")
    choices = data.get("choices") or []
    if not choices:
        raise ProviderError("response had no choices", kind="server")
    choice = choices[0]
    message = choice.get("message") or {}
    calls = [
        ToolCall(
            id=call.get("id") or f"call_{index}",
            name=(call.get("function") or {}).get("name", ""),
            arguments=_arguments_text((call.get("function") or {}).get("arguments")),
        )
        for index, call in enumerate(message.get("tool_calls") or [])
    ]
    return ChatResponse(
        text=_text_of(message.get("content")),
        tool_calls=calls,
        usage=openai_usage(data.get("usage")),
        model=model,
        stop_reason=choice.get("finish_reason"),
    )


class OpenAICompatProvider:
    def __init__(
        self,
        http: HttpClient,
        *,
        max_tokens_field: str = "max_tokens",
        stream_usage: bool = True,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.http = http
        self.max_tokens_field = max_tokens_field
        self.stream_usage = stream_usage
        self.extra_body = extra_body or {}

    def _payload(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [to_openai_message(m) for m in messages],
            self.max_tokens_field: max_tokens,
            **self.extra_body,
        }
        openai_tools = to_openai_tools(tools)
        if openai_tools:
            payload["tools"] = openai_tools
        return payload

    async def chat(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        *,
        max_tokens: int,
        timeout: float,
    ) -> ChatResponse:
        payload = self._payload(model, messages, tools, max_tokens)
        data = await self.http.post_json("/chat/completions", payload, timeout=timeout)
        return parse_completion(data, model)

    async def stream(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        *,
        max_tokens: int,
        timeout: float,
    ) -> AsyncIterator[StreamEvent]:
        payload = self._payload(model, messages, tools, max_tokens)
        payload["stream"] = True
        if self.stream_usage:
            payload["stream_options"] = {"include_usage": True}

        text: list[str] = []
        slots: dict[int, dict[str, str]] = {}
        usage = Usage(known=False)  # until a chunk carries it
        stop_reason: str | None = None
        async with self.http.stream_lines("/chat/completions", payload, timeout=timeout) as lines:
            async for data in sse_data(lines):
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if chunk.get("error"):
                    raise ProviderError(f"stream error: {chunk['error']}", kind="server")
                if chunk.get("usage"):
                    usage = openai_usage(chunk["usage"])
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    piece = _text_of(delta.get("content"))
                    if piece:
                        text.append(piece)
                        yield TextDelta(piece)
                    for call in delta.get("tool_calls") or []:
                        slot = slots.setdefault(
                            call.get("index", 0), {"id": "", "name": "", "arguments": ""}
                        )
                        if call.get("id"):
                            slot["id"] = call["id"]
                        function = call.get("function") or {}
                        name = function.get("name")
                        if name and name != slot["name"]:
                            slot["name"] += name
                        slot["arguments"] += _arguments_text(function.get("arguments"))
                    if choice.get("finish_reason"):
                        stop_reason = choice["finish_reason"]

        calls = [
            ToolCall(
                id=slot["id"] or f"call_{index}", name=slot["name"], arguments=slot["arguments"]
            )
            for index, slot in sorted(slots.items())
        ]
        yield StreamDone(
            ChatResponse(
                text="".join(text),
                tool_calls=calls,
                usage=usage,
                model=model,
                stop_reason=stop_reason,
            )
        )
