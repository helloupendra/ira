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
    "be done without. They may speak English, Hindi or Hinglish. Finding, reading, looking at "
    "something or being told about it is done without any of these actions, so it asks for none "
    "of them, unless what they asked to read must first be brought to the front. An action that "
    "merely could be useful, or that its name makes sound related, is not asked for. Most words "
    "ask for none or one.\n"
    'Examples. "Find the landlord\'s mail and say what it asks": none, neither writing a mail '
    'nor opening an app nor typing. "kal ka missed call dekho, number batao": none, not placing '
    'a call. "contract file dhundo, amount batao": none. "chrome ka report tab aage lao": '
    'showing that tab. "Sam ko bolo late hoon": sending that message.\n'
    "Answer with a JSON array of the names and nothing else, [] if none."
)
# A read is another question. Asking about something asks to look at it, and what it costs to be
# wrong differs: a read goes only to the person, and a false "I can't" is worse than a slow answer.
READ_RULE = (
    "You judge one thing: could each of these reads help answer what the person said? They may "
    "speak English, Hindi or Hinglish. A question about something asks to look at it. Leave one "
    "out only when it has nothing to do with their words, as reading messages has nothing to do "
    "with opening an app. Answer with a JSON array of the names and nothing else."
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
    """The check for one turn. `said`: what the person said, never anything read. Each action is
    asked about once a turn. `nothing_named`: no device is named in this message or the last."""

    def __init__(
        self, gateway: Gateway, said: list[str], tier: str = "default", seconds: float | None = None
    ) -> None:
        self.gateway = gateway
        self.said = said
        self.tier = tier
        self.seconds = seconds
        self.nothing_named = False
        self.known: dict[str, bool] = {}
        self.unreadable = 0
        self.calls = 0
        self.elapsed = 0.0

    async def which(self, actions: dict[str, str]) -> set[str]:
        """Of these actions, {name: what it does}, the ones the words ask for."""
        unknown = {n: d for n, d in actions.items() if n not in self.known}
        if unknown:
            yes = await self._ask(unknown, RULE) or set()
            self.known.update({name: name in yes for name in unknown})
        return {name for name in actions if self.known[name]}

    async def allows(self, name: str, description: str) -> bool:
        return name in await self.which({name: description})

    async def may_propose(self, name: str, description: str) -> bool:
        """Whether an act may be put to them on a card, with nothing read. No answer is a yes: the
        card is what stops it."""
        if name not in self.known:
            yes = await self._ask({name: description}, RULE)
            if yes is None:
                return True
            self.known[name] = name in yes
        return self.known[name]

    async def may_read(self, name: str, description: str) -> bool:
        """Whether a read has anything to do with what they said. No answer is a yes: it goes only
        to them."""
        if name not in self.known:
            yes = await self._ask({name: description}, READ_RULE)
            self.known[name] = yes is None or name in yes
        return self.known[name]

    async def _ask(self, actions: dict[str, str], rule: str) -> set[str] | None:
        """The names the answer says, or None when there is no answer to go by."""
        listed = "\n".join(f"- {name}: {_short(text)}" for name, text in sorted(actions.items()))
        said = "\n".join(f"- {words}" for words in self.said)
        messages = [
            Message(role="system", content=rule),
            Message(role="user", content=f"The person said:\n{said}\n\nActions:\n{listed}"),
        ]
        began = time.monotonic()
        self.calls += 1
        try:
            response = await self.gateway.chat(
                messages, None, tier=self.tier, purpose="asked", seconds=self.seconds
            )
        except GatewayError as exc:
            log.warning("the asked-for check failed: %s", exc)
            return None
        finally:
            self.elapsed += time.monotonic() - began
        answer = response.text or ""
        if not _ARRAY.search(answer):
            self.unreadable += 1
            log.warning("the asked-for check gave no list (%d characters)", len(answer))
            return None
        return _names(answer, set(actions))
