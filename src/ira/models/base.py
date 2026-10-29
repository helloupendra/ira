"""Provider-neutral chat types shared by every model provider."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant", "tool"]

# Error kinds a provider can raise. The gateway falls back on every kind; the
# kind is kept for the call log and for choosing a cool-down.
ErrorKind = Literal[
    "capacity", "timeout", "auth", "bad_request", "too_long", "server", "network", "error"
]
# Errors that say the request was wrong, not that the model is down: never a cool-down.
REQUEST_ERRORS = ("bad_request", "too_long")


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON text exactly as the model produced it

    def parsed_arguments(self) -> dict[str, Any] | None:
        """The arguments as a dict, or None when they are not a JSON object.

        An empty string counts as ``{}``: some providers send it for tools
        without parameters.
        """
        if not self.arguments or not self.arguments.strip():
            return {}
        try:
            value = json.loads(self.arguments)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def replay_arguments(self) -> str:
        """Arguments safe to send back to a provider in the conversation history.

        A provider rejects the whole conversation if an earlier tool call
        carries arguments that are not a JSON object, so those are replayed as
        ``{}``. The tool result already told the model what went wrong.
        """
        parsed = self.parsed_arguments()
        if parsed is None:
            return "{}"
        return self.arguments if self.arguments.strip() else "{}"


@dataclass
class Message:
    role: Role
    content: str | list[dict[str, Any]] | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # set on role="tool"
    name: str | None = None  # tool name on role="tool"
    # Kept with the transcript only; providers never send it.
    action_id: str | None = None  # role="tool": the action this call proposed
    model: str | None = None  # role="assistant": the provider:model that wrote it
    private: bool = False  # role="tool": a device's output, shown only to its own user

    @property
    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            return "".join(p.get("text", "") for p in self.content if p.get("type") == "text")
        return ""


@dataclass
class Usage:
    """Tokens a call used. input_tokens counts all of the input, cached or not; of them,
    cached_input_tokens were read from the provider's cache and cache_write_tokens written to
    it, each priced at its own rate. known is False when the provider said nothing: such a
    call's cost is unknown, never $0."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    known: bool = True

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cached_input_tokens + other.cached_input_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
            self.known and other.known,
        )


def openai_usage(usage: dict[str, Any] | None) -> Usage:
    """An OpenAI-style usage object: prompt_tokens include the cached ones."""
    if not usage:
        return Usage(known=False)
    details = usage.get("prompt_tokens_details") or {}
    return Usage(
        usage.get("prompt_tokens") or 0,
        usage.get("completion_tokens") or 0,
        cached_input_tokens=details.get("cached_tokens") or 0,
    )


def anthropic_usage(usage: dict[str, Any] | None, output_tokens: int | None = None) -> Usage:
    """Anthropic's usage: input_tokens leaves out what was read from or written to the cache."""
    if not usage:
        return Usage(known=False)
    read = usage.get("cache_read_input_tokens") or 0
    written = usage.get("cache_creation_input_tokens") or 0
    return Usage(
        (usage.get("input_tokens") or 0) + read + written,
        output_tokens if output_tokens is not None else (usage.get("output_tokens") or 0),
        cached_input_tokens=read,
        cache_write_tokens=written,
    )


@dataclass
class ChatResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""  # "provider:model" reference that answered
    stop_reason: str | None = None
    attempts: int = 1
    cost_usd: float | None = None


@dataclass
class TextDelta:
    text: str


@dataclass
class StreamDone:
    response: ChatResponse


StreamEvent = TextDelta | StreamDone


class ProviderError(Exception):
    """A failed model call, already stripped of credentials."""

    def __init__(
        self,
        message: str,
        *,
        kind: ErrorKind = "error",
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after


class ChatProvider(Protocol):
    """What the gateway needs from a provider. ``model`` is the provider's own id."""

    async def chat(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        *,
        max_tokens: int,
        timeout: float,
    ) -> ChatResponse: ...

    def stream(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        *,
        max_tokens: int,
        timeout: float,
    ) -> AsyncIterator[StreamEvent]: ...
