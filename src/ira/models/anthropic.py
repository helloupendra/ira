"""The Anthropic Messages API, with tool use and streaming."""

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
)
from ira.models.http import HttpClient, classify_status, sse_data

API_VERSION = "2023-06-01"


def _blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        return [p for p in content if isinstance(p, dict) and p.get("type") == "text"]
    if content:
        return [{"type": "text", "text": str(content)}]
    return []


def to_anthropic(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Split out the system prompt and convert the rest to Messages API turns.

    Tool results become ``tool_result`` blocks in a user turn, and consecutive
    turns from the same role are merged, because the API requires the roles
    to alternate.
    """
    system = "\n\n".join(m.text for m in messages if m.role == "system" and m.text)
    turns: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            role = "user"
            blocks = [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id or "",
                    "content": message.text,
                }
            ]
        elif message.role == "assistant":
            role = "assistant"
            blocks = _blocks(message.content)
            for call in message.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.parsed_arguments() or {},
                    }
                )
        else:
            role = "user"
            blocks = _blocks(message.content)
        if not blocks:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"].extend(blocks)
        else:
            turns.append({"role": role, "content": blocks})
    return system, turns


def to_anthropic_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "name": spec["name"],
            "description": spec.get("description", ""),
            "input_schema": spec.get("parameters") or {"type": "object", "properties": {}},
        }
        for spec in tools
    ]


def parse_message(data: dict[str, Any], model: str) -> ChatResponse:
    if data.get("type") == "error":
        error = data.get("error") or {}
        raise ProviderError(f"provider error: {error.get('message', error)}", kind="server")
    text: list[str] = []
    calls: list[ToolCall] = []
    for block in data.get("content") or []:
        if block.get("type") == "text":
            text.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            calls.append(
                ToolCall(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    arguments=json.dumps(block.get("input") or {}),
                )
            )
    usage = data.get("usage") or {}
    return ChatResponse(
        text="".join(text),
        tool_calls=calls,
        usage=Usage(usage.get("input_tokens") or 0, usage.get("output_tokens") or 0),
        model=model,
        stop_reason=data.get("stop_reason"),
    )


def _stream_error(event: dict[str, Any]) -> ProviderError:
    error = event.get("error") or {}
    kind_text = str(error.get("type", ""))
    message = str(error.get("message", "stream error"))
    kind = "capacity" if "overloaded" in kind_text else classify_status(500, message)
    return ProviderError(f"stream error: {kind_text} {message}".strip(), kind=kind)


class AnthropicProvider:
    def __init__(self, http: HttpClient, *, api_version: str = API_VERSION) -> None:
        self.http = http
        self.http.extra_headers.setdefault("anthropic-version", api_version)

    def _payload(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        system, turns = to_anthropic(messages)
        payload: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": turns}
        if system:
            payload["system"] = system
        anthropic_tools = to_anthropic_tools(tools)
        if anthropic_tools:
            payload["tools"] = anthropic_tools
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
        data = await self.http.post_json("/v1/messages", payload, timeout=timeout)
        return parse_message(data, model)

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

        text: list[str] = []
        blocks: dict[int, dict[str, str]] = {}
        input_tokens = output_tokens = 0
        stop_reason: str | None = None
        async with self.http.stream_lines("/v1/messages", payload, timeout=timeout) as lines:
            async for data in sse_data(lines):
                try:
                    event = json.loads(data)
                except ValueError:
                    continue
                kind = event.get("type")
                if kind == "error":
                    raise _stream_error(event)
                if kind == "message_start":
                    usage = (event.get("message") or {}).get("usage") or {}
                    input_tokens = usage.get("input_tokens") or 0
                elif kind == "content_block_start":
                    block = event.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        blocks[event.get("index", 0)] = {
                            "id": block.get("id", ""),
                            "name": block.get("name", ""),
                            "json": "",
                        }
                elif kind == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        text.append(delta["text"])
                        yield TextDelta(delta["text"])
                    elif delta.get("type") == "input_json_delta":
                        slot = blocks.get(event.get("index", 0))
                        if slot is not None:
                            slot["json"] += delta.get("partial_json", "")
                elif kind == "message_delta":
                    stop_reason = (event.get("delta") or {}).get("stop_reason") or stop_reason
                    output_tokens = (event.get("usage") or {}).get("output_tokens") or output_tokens
                elif kind == "message_stop":
                    break

        calls = [
            ToolCall(id=b["id"], name=b["name"], arguments=b["json"] or "{}")
            for _, b in sorted(blocks.items())
        ]
        yield StreamDone(
            ChatResponse(
                text="".join(text),
                tool_calls=calls,
                usage=Usage(input_tokens, output_tokens),
                model=model,
                stop_reason=stop_reason,
            )
        )
