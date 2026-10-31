"""Tool calls a model wrote as text instead of making them.

Now and then a model writes its call into the answer: Kimi K2.5 on Bedrock
has written ``<invoke name="screen_read">`` and its own
``functions.screen_read:0 <|tool_call_argument_begin|> {}`` markup (sometimes
without ``functions.``), and
Qwen-style models write ``<tool_call>{"name": ...}</tool_call>``. On a live
call on 31 Oct 2026 the answer was ``<tool_call>`` with the tool's name as a
tag of its own, ``<trading_desk>``, then the arguments; GLM's own template
writes the name bare, then ``<arg_key>``/``<arg_value>`` pairs. The person
would see that markup and the tool would never run. ``recover`` turns such
text back into calls, only for tools that were offered in that turn, and
returns the prose that came before the markup.

While an answer streams, ``MarkupGate`` holds text back from where such markup
may be starting, so it is never shown or spoken; ``before_markup`` gives the
prose of an answer whose markup cannot be run, to show that instead.
"""

from __future__ import annotations

import json
import re
import secrets
from typing import Any

from ira.models.base import ToolCall

_INVOKE = re.compile(r'<invoke\s+name="([A-Za-z0-9_-]{1,64})"\s*>(.*?)</invoke>', re.S)
_PARAMETER = re.compile(r'<parameter\s+name="([^"]{1,64})"\s*>(.*?)</parameter>', re.S)
_KIMI = re.compile(
    r"(?:functions\.)?([A-Za-z0-9_-]{1,64}):\d+\s*<\|tool_call_argument_begin\|>\s*(.*?)\s*"
    r"<\|tool_call_end\|>",
    re.S,
)
_HERMES = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
# The name as a tag: <tool_call><trading_desk>{...}</trading_desk>?</tool_call>.
_TAGGED = re.compile(
    r"<tool_call>\s*<([A-Za-z0-9_-]{1,64})>\s*(\{.*?\})\s*(?:</\1>\s*)?</tool_call>", re.S
)
# The name bare, then the arguments as JSON or as GLM's key and value pairs.
_NAMED = re.compile(r"<tool_call>\s*([A-Za-z0-9_-]{1,64})\s*(\{.*?\})\s*</tool_call>", re.S)
_GLM = re.compile(
    r"<tool_call>\s*([A-Za-z0-9_-]{1,64})\s*"
    r"((?:<arg_key>.*?</arg_key>\s*<arg_value>.*?</arg_value>\s*)*)</tool_call>",
    re.S,
)
_GLM_ARGUMENT = re.compile(r"<arg_key>(.*?)</arg_key>\s*<arg_value>(.*?)</arg_value>", re.S)
_WRAPPERS = re.compile(
    r"</?function_calls>|<\|tool_calls_section_(begin|end)\|>|<\|tool_call_begin\|>", re.S
)
# Where a call written as text starts, in any of the ways above or DeepSeek's DSML.
_START = re.compile(r"<tool_call>|<invoke\s|</?function_calls>|<\|tool_call|<｜DSML｜|<\|DSML\|")
_STARTS = (
    "<tool_call>",
    "<invoke",
    "<function_calls>",
    "</function_calls>",
    "<|tool_call",
    "<｜DSML｜",
    "<|DSML|",
)


def _value(text: str) -> Any:
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        return text


def _object(text: str) -> dict[str, Any] | None:
    value = _value(text) if text.strip() else {}
    if not isinstance(value, dict):
        return None
    return {k: v for k, v in value.items() if k}  # Kimi has written {"": {}} for "nothing"


def _found(text: str) -> list[tuple[int, str, dict[str, Any] | None]]:
    """(where it starts, the tool's name, its arguments) for every call written as text."""
    found: list[tuple[int, str, dict[str, Any] | None]] = []
    for match in _INVOKE.finditer(text):
        parameters = {k: _value(v) for k, v in _PARAMETER.findall(match.group(2))}
        if set(parameters) == {"input"} and isinstance(parameters["input"], dict):
            parameters = parameters["input"]  # some write the whole object as one parameter
        found.append((match.start(), match.group(1), parameters))
    for match in _KIMI.finditer(text):
        found.append((match.start(), match.group(1), _object(match.group(2))))
    for match in _HERMES.finditer(text):
        call = _object(match.group(1)) or {}
        arguments = call.get("arguments", call.get("parameters", {}))
        if isinstance(arguments, str):
            arguments = _object(arguments)
        found.append(
            (
                match.start(),
                str(call.get("name", "")),
                arguments if isinstance(arguments, dict) else None,
            )
        )
    for match in _TAGGED.finditer(text):
        found.append((match.start(), match.group(1), _object(match.group(2))))
    for match in _NAMED.finditer(text):
        found.append((match.start(), match.group(1), _object(match.group(2))))
    for match in _GLM.finditer(text):
        arguments = {k.strip(): _value(v) for k, v in _GLM_ARGUMENT.findall(match.group(2))}
        found.append((match.start(), match.group(1), arguments))
    return sorted(found, key=lambda item: item[0])


def recover(text: str, offered: set[str]) -> tuple[str, list[ToolCall]]:
    """(the prose before the markup, the calls) when every call names an offered tool with
    an object of arguments; otherwise (text, []) and the text stays as it was."""
    found = _found(text or "")
    if not found or any(name not in offered or args is None for _, name, args in found):
        return text, []
    calls = [
        ToolCall(f"recovered_{secrets.token_hex(4)}", name, json.dumps(args, ensure_ascii=False))
        for _, name, args in found
    ]
    prose = _WRAPPERS.sub("", text[: found[0][0]]).strip()
    return prose, calls


def before_markup(text: str) -> str | None:
    """The prose before a call written as text, or None when the text has no such markup."""
    match = _START.search(text or "")
    if match is None:
        return None
    return _WRAPPERS.sub("", text[: match.start()]).strip()


class MarkupGate:
    """Streamed text with any call written as text kept out: a piece that may be the start
    of such markup is held until the next piece shows whether it is, and once markup has
    started, nothing more of that answer goes out."""

    def __init__(self) -> None:
        self._held = ""
        self.cut = False

    def feed(self, piece: str) -> str:
        if self.cut:
            return ""
        text = self._held + piece
        match = _START.search(text)
        if match:
            self.cut, self._held = True, ""
            return text[: match.start()]
        at = text.rfind("<")
        tail = text[at:] if at != -1 else ""
        if tail and any(start.startswith(tail) for start in _STARTS):
            self._held = tail
            return text[:at]
        self._held = ""
        return text

    def flush(self) -> str:
        """What is still held when the answer ends: text, unless markup had started."""
        held, self._held = self._held, ""
        return "" if self.cut else held
