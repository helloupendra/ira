"""The device WebSocket's frames and limits: what a device may say, checked before use.

Frames are JSON text objects told apart by ``type``:

* device -> server: ``hello``, ``result``, ``event``, ``ping``, ``pong``;
* server -> device: ``welcome``, ``call``, ``error``, ``ping``, ``pong``, and
  ``event`` (to an Android device, so it can speak its user's events).

Everything a device sends is untrusted: tool lists are checked against the
limits here, event text is stripped of markup and cut to length.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from typing import Any

MAX_FRAME_BYTES = 1024 * 1024
CALL_SECONDS = 25.0
MAX_IN_FLIGHT = 4
MAX_TOOLS = 30
PING_SECONDS = 30.0
SILENCE_SECONDS = 90.0
HELLO_SECONDS = 15.0
EVENT_SECONDS = 30.0
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
SKILL_NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
KINDS = ("mac", "android")
EVENTS = ("watch_done", "task_done", "task_failed")
MAX_DESCRIPTION = 1000
MAX_SCHEMA_BYTES = 8 * 1024
MAX_TITLE = 120
MAX_TEXT = 1000
MAX_EVENT_DATA_BYTES = 4 * 1024
MAX_LABEL = 60
MAX_VERSION = 40
DEFAULT_DEVICE_TIER = 2  # a tool that does not say is treated as needing a yes

# Close codes (4000-4999 are the application's own).
CLOSE_REPLACED = 4000
CLOSE_BAD_HELLO = 4400
CLOSE_UNAUTHORIZED = 4401
CLOSE_REVOKED = 4403
CLOSE_SILENT = 4408
CLOSE_TOO_BIG = 1009


class ProtocolError(ValueError):
    """A frame the server refuses; the message is safe to send back to the device."""


@dataclass(frozen=True)
class DeviceTool:
    name: str
    description: str
    parameters: dict[str, Any]
    skill: str
    tier: int

    def public(self) -> dict[str, Any]:
        """What the server keeps and shows: never a call's arguments or output."""
        return {
            "name": self.name,
            "description": self.description,
            "skill": self.skill,
            "tier": self.tier,
        }


@dataclass(frozen=True)
class Hello:
    kind: str
    label: str
    version: str
    tools: tuple[DeviceTool, ...]


def decode(text: str) -> dict[str, Any]:
    """One frame: at most 1 MB of JSON holding an object with a string ``type``."""
    if len(text.encode("utf-8", "surrogatepass")) > MAX_FRAME_BYTES:
        raise ProtocolError("frames are 1 MB at most")
    try:
        frame = json.loads(text)
    except ValueError:
        raise ProtocolError("a frame must be JSON") from None
    if not isinstance(frame, dict) or not isinstance(frame.get("type"), str):
        raise ProtocolError('a frame must be an object with a "type"')
    return frame


def encode(frame: dict[str, Any]) -> str:
    return json.dumps(frame, ensure_ascii=False, separators=(",", ":"))


def clean_line(value: Any, limit: int) -> str:
    """One line of plain text: no markup, no control characters, cut to ``limit``."""
    text = strip_markup(str(value or ""))
    return " ".join(text.split())[:limit]


_TAG = re.compile(r"<[^>]{0,500}>")
_MARKDOWN = re.compile(r"(\*\*|__|`{1,3}|~~|^#{1,6}\s+|^\s*>\s?)", re.MULTILINE)
_LINK = re.compile(r"!?\[([^\]]{0,300})\]\([^)]{0,500}\)")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_markup(text: str) -> str:
    """Plain text from HTML or markdown a device sent: tags, links and emphasis go."""
    text = _LINK.sub(r"\1", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = _TAG.sub(" ", text)  # tags that were escaped once
    text = _MARKDOWN.sub("", text)
    return _CONTROL.sub("", text)


def clean_text(value: Any, limit: int) -> str:
    """Plain text that keeps its line breaks, cut to ``limit``."""
    lines = [" ".join(line.split()) for line in strip_markup(str(value or "")).splitlines()]
    return "\n".join(line for line in lines if line)[:limit]


def _tool(raw: Any, seen: set[str]) -> DeviceTool:
    if not isinstance(raw, dict):
        raise ProtocolError("each tool must be an object")
    name = raw.get("name")
    if not isinstance(name, str) or not TOOL_NAME.fullmatch(name):
        shown = name if isinstance(name, str) else type(name).__name__
        raise ProtocolError(f"bad tool name '{str(shown)[:60]}': names match {TOOL_NAME.pattern}")
    if name in seen:
        raise ProtocolError(f"tool '{name}' is listed twice")
    seen.add(name)
    description = raw.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ProtocolError(f"tool '{name}' needs a description")
    parameters = raw.get("parameters", {"type": "object", "properties": {}})
    if not isinstance(parameters, dict) or parameters.get("type", "object") != "object":
        raise ProtocolError(f"tool '{name}': parameters must be a JSON Schema object")
    if len(json.dumps(parameters)) > MAX_SCHEMA_BYTES:
        raise ProtocolError(f"tool '{name}': parameters are larger than 8 KB")
    parameters = {"type": "object", "properties": {}, **parameters}
    skill = raw.get("skill", name.split("_", 1)[0])
    if not isinstance(skill, str) or not SKILL_NAME.fullmatch(skill):
        raise ProtocolError(f"tool '{name}': skill must match {SKILL_NAME.pattern}")
    tier = raw.get("tier", DEFAULT_DEVICE_TIER)
    if not isinstance(tier, int) or isinstance(tier, bool) or tier not in (0, 1, 2, 3):
        raise ProtocolError(f"tool '{name}': tier must be 0, 1, 2 or 3")
    return DeviceTool(
        name=name,
        description=clean_line(description, MAX_DESCRIPTION),
        parameters=parameters,
        skill=skill,
        tier=tier,
    )


def parse_hello(frame: dict[str, Any], expected_kind: str) -> Hello:
    """Check a device's hello: its kind, and a tool list within the limits."""
    if frame.get("type") != "hello":
        raise ProtocolError("the first frame must be a hello")
    kind = frame.get("kind")
    if kind != expected_kind:
        raise ProtocolError(f"this device was paired as '{expected_kind}', not '{kind}'")
    tools = frame.get("tools", [])
    if not isinstance(tools, list):
        raise ProtocolError("tools must be a list")
    if len(tools) > MAX_TOOLS:
        raise ProtocolError(f"a device offers {MAX_TOOLS} tools at most")
    seen: set[str] = set()
    parsed = tuple(_tool(raw, seen) for raw in tools)
    return Hello(
        kind=kind,
        label=clean_line(frame.get("label"), MAX_LABEL),
        version=clean_line(frame.get("version"), MAX_VERSION),
        tools=parsed,
    )


@dataclass(frozen=True)
class Event:
    event: str
    title: str
    text: str
    data: dict[str, Any]


def parse_event(frame: dict[str, Any]) -> Event:
    name = frame.get("event")
    if name not in EVENTS:
        raise ProtocolError(f"event must be one of {', '.join(EVENTS)}")
    data = frame.get("data") or {}
    if not isinstance(data, dict) or len(json.dumps(data, default=str)) > MAX_EVENT_DATA_BYTES:
        data = {}
    title = clean_line(frame.get("title"), MAX_TITLE)
    text = clean_text(frame.get("text"), MAX_TEXT)
    if not title and not text:
        raise ProtocolError("an event needs a title or a text")
    return Event(
        event=name, title=title or text.split("\n", 1)[0][:MAX_TITLE], text=text, data=data
    )
