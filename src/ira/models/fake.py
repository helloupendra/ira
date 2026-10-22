"""Providers that need no network: a scripted one for tests and a demo router.

``ScriptedProvider`` replays a list of responses or exceptions, and records
what it was sent, so tests can assert on the exact conversation.

``RouterProvider`` lets the demo run with no API key at all. It is not a
language model: it picks a tool by matching words of the tool's name against
the message (and a few Hindi and Hinglish words: "kaunse", "kitna", "batana"),
pulls arguments out with simple patterns (``key=value``, ISO dates, ``for
<Name>``, numbers, "<word> tab"), and reads tool results back as text.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from ira.models.base import (
    ChatResponse,
    Message,
    StreamDone,
    StreamEvent,
    TextDelta,
    ToolCall,
    Usage,
)
from ira.tools.personal import unwrap


def _estimate_tokens(messages: list[Message]) -> int:
    return sum(len(m.text) for m in messages) // 4 + 1


class ScriptedProvider:
    """Each call takes the next item: a ChatResponse, a str, or an exception to raise."""

    def __init__(self, script: list[Any] | None = None, *, delay: float = 0.0) -> None:
        self.script = list(script or [])
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    async def _next(
        self, model: str, messages: list[Message], tools: list[dict[str, Any]] | None
    ) -> ChatResponse:
        self.calls.append({"model": model, "messages": list(messages), "tools": tools})
        if self.delay:
            import asyncio

            await asyncio.sleep(self.delay)
        if not self.script:
            return ChatResponse(text="(script exhausted)", model=model)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, str):
            item = ChatResponse(text=item)
        item.model = model
        if not item.usage.input_tokens:
            item.usage = Usage(_estimate_tokens(messages), max(1, len(item.text) // 4))
        return item

    async def chat(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        *,
        max_tokens: int,
        timeout: float,
    ) -> ChatResponse:
        return await self._next(model, messages, tools)

    async def stream(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        *,
        max_tokens: int,
        timeout: float,
    ) -> AsyncIterator[StreamEvent]:
        response = await self._next(model, messages, tools)
        for word in re.findall(r"\S+\s*", response.text):
            yield TextDelta(word)
        yield StreamDone(response)


# --- demo router -----------------------------------------------------------------

_KV = re.compile(r"(\w+)\s*[=:]\s*(\"[^\"]*\"|'[^']*'|[^\s,]+)")
_DATETIME = re.compile(r"\b(\d{4}-\d{2}-\d{2})[ T](\d{1,2}:\d{2})\b")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_INT = re.compile(r"(?<![\d:-])\b(\d{1,9})\b(?![\d:-])")
_FOR_NAME = re.compile(r"\b(?:for|named|called)\s+([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*)")
_WORD = re.compile(r"[a-z]+")
# "<word> tab", "<word> wale tab": the tab someone means.
_TAB_NAME = re.compile(r"\b([a-z0-9][\w.-]*)\s+(?:wale\s+|waale\s+|vale\s+)?tabs?\b", re.I)

# Words people use, in English, Hindi and Hinglish, for the words in tool names.
SYNONYMS = {
    "kaunse": "list",
    "konse": "list",
    "kaun": "list",
    "khule": "list",
    "khula": "list",
    "open": "list",
    "saare": "list",
    "sab": "list",
    "kitna": "read",
    "kitni": "read",
    "hua": "read",
    "progress": "read",
    "status": "read",
    "padho": "read",
    "batana": "watch",
    "khatam": "watch",
    "jab": "watch",
    "notify": "watch",
    "finish": "watch",
    "finishes": "watch",
    "chrome": "browser",
    "safari": "browser",
    "arc": "browser",
    "edge": "browser",
    "brave": "browser",
    "khabar": "news",
    "khabren": "news",
    "samachar": "news",
    "headlines": "news",
    "dhundo": "search",
    "khojo": "search",
    "google": "search",
}
# Words that never name a tab or make up a search query.
_FILLER = frozenset(
    [
        "a",
        "an",
        "the",
        "that",
        "this",
        "us",
        "is",
        "it",
        "my",
        "me",
        "mera",
        "mere",
        "meri",
        "wo",
        "woh",
        "yeh",
        "ye",
        "mein",
        "main",
        "ka",
        "ki",
        "ke",
        "ko",
        "par",
        "pe",
        "hai",
        "hain",
        "ho",
        "kya",
        "kaunse",
        "konse",
        "chrome",
        "open",
        "khule",
        "sab",
        "saare",
        "batao",
        "bata",
        "please",
        "about",
        "for",
        "on",
        "of",
        "in",
        "search",
        "dhundo",
        "khojo",
        "web",
        "google",
        "news",
        "khabar",
        "khabren",
        "samachar",
        "aaj",
        "latest",
        "abhi",
        "tab",
        "tabs",
    ]
)


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _words(text: str) -> set[str]:
    words = {_stem(w) for w in _WORD.findall(text.lower())}
    return words | {_stem(SYNONYMS[w]) for w in words if w in SYNONYMS}


class RouterProvider:
    """Keyword routing over the registered tools, for a no-key demo."""

    def __init__(self, today: dt.date | None = None) -> None:
        self._today = today

    @property
    def today(self) -> dt.date:
        return self._today or dt.date.today()

    async def chat(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        *,
        max_tokens: int,
        timeout: float,
    ) -> ChatResponse:
        response = self._respond(messages, tools or [])
        response.model = model
        response.usage = Usage(_estimate_tokens(messages), max(1, len(response.text) // 4))
        return response

    async def stream(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        *,
        max_tokens: int,
        timeout: float,
    ) -> AsyncIterator[StreamEvent]:
        response = await self.chat(model, messages, tools, max_tokens=max_tokens, timeout=timeout)
        if response.text:
            yield TextDelta(response.text)
        yield StreamDone(response)

    # The routing itself.

    def _respond(self, messages: list[Message], tools: list[dict[str, Any]]) -> ChatResponse:
        last = messages[-1] if messages else Message(role="user", content="")
        if last.role == "tool":
            return ChatResponse(text=self._read_results(messages))
        tool = self._pick_tool(last.text, tools)
        if tool is None:
            return ChatResponse(text=self._help(tools))
        args, missing = self._extract_args(last.text, tool)
        if missing:
            example = " ".join(f'{name}="..."' for name in missing)
            return ChatResponse(
                text=f"To use {tool['name']} I need {', '.join(missing)}. "
                f"Try: {tool['name'].replace('_', ' ')} {example}"
            )
        call_id = f"demo_{len(messages)}"
        return ChatResponse(text="", tool_calls=[ToolCall(call_id, tool["name"], json.dumps(args))])

    def _pick_tool(self, text: str, tools: list[dict[str, Any]]) -> dict[str, Any] | None:
        words = _words(text)
        explicit = {k.lower() for k, _ in _KV.findall(text)}
        best, best_score = None, 0.0
        for spec in tools:
            parts = [_stem(p) for p in spec["name"].lower().split("_") if p]
            score = float(sum(1 for p in parts if p in words))
            if parts and parts[0] in words:
                score += 0.5  # the verb ("book", "cancel") says the most
            params = (spec.get("parameters") or {}).get("properties") or {}
            score += 2 * len(explicit & {name.lower() for name in params})
            if score > best_score:
                best, best_score = spec, score
        return best

    def _extract_args(self, text: str, tool: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        schema = tool.get("parameters") or {}
        properties: dict[str, Any] = schema.get("properties") or {}
        required: list[str] = schema.get("required") or []
        explicit = {k.lower(): v.strip("\"'") for k, v in _KV.findall(text)}
        lowered = text.lower()
        args: dict[str, Any] = {}
        for name, prop in properties.items():
            kind = prop.get("type")
            if name.lower() in explicit:
                value: Any = explicit[name.lower()]
            elif "slot" in name or "time" in name:
                match = _DATETIME.search(text)
                value = f"{match.group(1)} {match.group(2)}" if match else None
            elif "date" in name or prop.get("format") == "date":
                match = _DATE.search(text)
                if match:
                    value = match.group(0)
                elif "tomorrow" in lowered:
                    value = (self.today + dt.timedelta(days=1)).isoformat()
                elif "today" in lowered:
                    value = self.today.isoformat()
                else:
                    value = None
            elif kind == "integer":
                match = _INT.search(text)
                value = match.group(1) if match else None
            elif kind == "string" and "name" in name:
                match = _FOR_NAME.search(text)
                value = match.group(1) if match else None
            elif kind == "string" and name == "match":
                names = [m for m in _TAB_NAME.findall(text) if m.lower() not in _FILLER]
                value = names[0] if names else None
            elif kind == "string" and name == "query":
                kept = [w for w in re.findall(r"[\w.-]+", text) if w.lower() not in _FILLER]
                value = " ".join(kept) or None
            else:
                value = None
            if value is None:
                continue
            if kind == "integer":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            args[name] = value
        missing = [name for name in required if name not in args]
        return args, missing

    def _read_results(self, messages: list[Message]) -> str:
        results: list[str] = []
        for message in reversed(messages):
            if message.role != "tool":
                break
            results.append(message.text)
        lines: list[str] = []
        for raw in reversed(results):
            raw = unwrap(raw)  # a device's or the web's result, wrapped as data
            try:
                value = json.loads(raw)
            except ValueError:
                lines.append(raw)
                continue
            lines.append(_describe(value))
        return "\n".join(lines) or "Done."

    def _help(self, tools: list[dict[str, Any]]) -> str:
        if not tools:
            return "Demo mode: no tools are registered, so there is nothing to look up."
        names = ", ".join(spec["name"].replace("_", " ") for spec in tools)
        return (
            "I'm running in demo mode without a language model, so I match keywords. "
            f"Try asking about: {names}."
        )


def _describe(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("status") == "pending_confirmation":
            return (
                f"I've prepared this: {value.get('summary')}. Confirm it with your PIN to go ahead."
            )
        if "error" in value:
            return f"That did not work: {value['error']}"
        if isinstance(value.get("summary"), str):
            return value["summary"]
        return "\n".join(f"{k.replace('_', ' ')}: {_inline(v)}" for k, v in value.items())
    if isinstance(value, list):
        if not value:
            return "Nothing found."
        return "\n".join(f"- {_inline(item)}" for item in value)
    return str(value)


def _inline(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k.replace('_', ' ')} {_inline(v)}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(_inline(v) for v in value) if value else "none"
    return str(value)
