"""Whether the person's own words ask for an action: what lets an act follow a read in a turn.

A screen, a page or a mail may try to steer Ira, and the model that reads them cannot be trusted
to ignore them. So this is a separate, narrow question to a model that is given only what the
person said and what the action is. It never sees a tool's result or the conversation's past, so
nothing read can change its answer. An error, or an answer it cannot read, counts as no.
(docs/security.md, "What she reads cannot steer her".)
"""

from __future__ import annotations

import json
import logging
import re
import time

from ira.models.base import Message
from ira.models.gateway import Gateway, GatewayError

log = logging.getLogger(__name__)

RULE = (
    "You judge one thing: which of the listed actions the person's own words ask for, or cannot "
    "be done without. They may speak English, Hindi or Hinglish. Looking at something, or asking "
    "about it, does not ask to act on it, and an action that merely could be useful is not asked "
    "for. Answer with a JSON array of the names and nothing else, [] if none."
)
_ARRAY = re.compile(r"\[[^\[\]]*\]")
_FIRST_SENTENCE = re.compile(r"^.*?[.!?](?=\s|$)", re.DOTALL)


def _short(description: str) -> str:
    match = _FIRST_SENTENCE.match(description.strip())
    return (match.group(0) if match else description.strip())[:160]


def _names(answer: str, known: set[str]) -> set[str]:
    """The names in a model's answer. Its last array counts, and only names that were listed."""
    arrays = _ARRAY.findall(answer)
    if not arrays:
        return set()
    try:
        parsed = json.loads(arrays[-1])
    except ValueError:
        return set()
    return {name for name in parsed if isinstance(name, str) and name in known}


class AskedFor:
    """The check for one turn. `said`: this message, and while control of a device is on, the
    words that started it and the person's last few since. Never anything read. Each action is
    asked about once a turn."""

    def __init__(
        self, gateway: Gateway, said: list[str], tier: str = "default", seconds: float | None = None
    ) -> None:
        self.gateway = gateway
        self.said = said
        self.tier = tier
        self.seconds = seconds
        self.known: dict[str, bool] = {}
        self.unreadable = 0
        self.calls = 0
        self.elapsed = 0.0

    async def which(self, actions: dict[str, str]) -> set[str]:
        """Of these actions, {name: what it does}, the ones the words ask for."""
        unknown = {n: d for n, d in actions.items() if n not in self.known}
        if unknown:
            yes = await self._ask(unknown)
            self.known.update({name: name in yes for name in unknown})
        return {name for name in actions if self.known[name]}

    async def allows(self, name: str, description: str) -> bool:
        return name in await self.which({name: description})

    async def _ask(self, actions: dict[str, str]) -> set[str]:
        listed = "\n".join(f"- {name}: {_short(text)}" for name, text in sorted(actions.items()))
        said = "\n".join(f"- {words}" for words in self.said)
        messages = [
            Message(role="system", content=RULE),
            Message(role="user", content=f"The person said:\n{said}\n\nActions:\n{listed}"),
        ]
        began = time.monotonic()
        self.calls += 1
        try:
            response = await self.gateway.chat(
                messages, None, tier=self.tier, purpose="asked", seconds=self.seconds
            )
        except GatewayError as exc:
            log.warning("the asked-for check failed, so nothing passes it: %s", exc)
            return set()
        finally:
            self.elapsed += time.monotonic() - began
        answer = response.text or ""
        if not _ARRAY.search(answer):
            self.unreadable += 1
            log.warning("the asked-for check gave no list, so nothing passes it: %r", answer[:120])
        return _names(answer, set(actions))
