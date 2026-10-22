"""Tool calls a model wrote as text instead of making them.

Now and then a model writes its call into the answer: Kimi K2.5 on Bedrock
has written ``<invoke name="screen_read">`` and its own
``functions.screen_read:0 <|tool_call_argument_begin|> {}`` markup (sometimes
without ``functions.``), and
Qwen-style models write ``<tool_call>{"name": ...}</tool_call>``. The person
would see that markup and the tool would never run. ``recover`` turns such
text back into calls, only for tools that were offered in that turn, and
returns the prose that came before the markup.
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
_WRAPPERS = re.compile(
    r"</?function_calls>|<\|tool_calls_section_(begin|end)\|>|<\|tool_call_begin\|>", re.S
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
