"""Learning from what a person says: "main office nikal raha hoon" becomes an observation.

Only when they switched the ``conversation`` source on, and only for messages
that mention leaving, heading to or reaching somewhere (a word list in
English, Hinglish and Hindi decides that before any model is asked). A model
then names the movement, the place and the quote; the **quote check** keeps
it only if the quote is the person's own words, word for word, and the place
is in the quote or is a place they already named.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ira.learning.reminders import known_places
from ira.learning.service import LearningService
from ira.learning.store import LearningError, clean_label
from ira.models.base import Message
from ira.models.gateway import Gateway, GatewayError

log = logging.getLogger("ira.learning")

MOVING = re.compile(
    r"\b(nikal\w*|ja\s+raha|ja\s+rahi|jaa\s+raha|pahunch\w*|pohonch\w*|aa\s+gay[ai]|"
    r"reached|reaching|leaving|left|heading|on\s+my\s+way|arrived|going\s+to)\b"
    r"|निकल|पहुँच|पहुंच|जा\s+रहा|जा\s+रही|आ\s+गया|आ\s+गई",
    re.IGNORECASE,
)
KINDS = {"leave", "heading", "arrive"}
PROMPT = """\
You note where a person is going, from one message they wrote. Note only what \
they themselves say: leaving a place ("leave"), being on their way to a place \
("heading"), or having reached a place ("arrive"). Answer with JSON only:
{"observations": [{"kind": "leave" | "heading" | "arrive", "place": "the place as \
they named it", "quote": "their words, copied exactly from the message"}]}
If the message says none of these, answer {"observations": []}. Never guess a place."""

_PUNCTUATION = re.compile(r"[!-/:-@\[-`{-~।॥‘-‟…]")


def normal(text: str) -> str:
    return " ".join(_PUNCTUATION.sub(" ", text.lower()).split())


def checked(message: str, quote: str, place: str, known: set[str]) -> str | None:
    """The place's label if the quote is the person's own words and names the place."""
    said, words, where = normal(message), normal(quote), normal(place)
    if not words or not where or f" {words} " not in f" {said} ":
        return None
    for label in known:
        if normal(label) == where:
            return label
    if f" {where} " not in f" {words} ":
        return None
    try:
        return clean_label(place[:1].upper() + place[1:])
    except LearningError:
        return None


def _json(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        value = json.loads(text[start : end + 1])
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


async def extract(
    service: LearningService, gateway: Gateway, user_id: int, message: str, *, tier: str
) -> list[int]:
    """Record what the message says about the person's movements; their ids."""
    if not service.allowed(user_id, "conversation") or not MOVING.search(message):
        return []
    try:
        response = await gateway.chat(
            [Message(role="system", content=PROMPT), Message(role="user", content=message)],
            None,
            tier=tier,
            purpose="learn",
        )
    except (GatewayError, KeyError) as exc:
        log.warning("learning from a message failed: %s", type(exc).__name__)
        return []
    items = _json(response.text).get("observations")
    if not isinstance(items, list):
        return []
    known = known_places(service, user_id)
    kept = []
    for item in items[:3]:
        if not isinstance(item, dict) or item.get("kind") not in KINDS:
            continue
        quote, place = str(item.get("quote") or ""), str(item.get("place") or "")
        label = checked(message, quote, place, known)
        if label is None:
            continue
        observation = await service.record(
            user_id,
            str(item["kind"]),
            "conversation",
            label=label,
            detail={"quote": " ".join(quote.split())[:200]},
        )
        if observation is not None:
            kept.append(observation)
    return kept
