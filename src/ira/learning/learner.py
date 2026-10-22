"""The learner: patterns become learnings through the proof gate, and active ones are used.

States of a learning:

* ``proposed``: seen, but not enough yet (fewer than 8 days, under 14 days, or
  too spread out);
* ``ready``: the evidence passes; Ira asks the person once, and it becomes
  ``asked``;
* ``active`` after their yes, ``rejected`` after their no (never asked again);
* ``faded``: active, but not seen for 21 days; it leaves the prompt;
* ``changed``: active, but the last 5 or more days fall outside its middle
  half; Ira asks again with the new numbers.

Active learnings go into the person's prompt (8 lines, 600 characters at
most), and, if they switched nudges on, a time routine is nudged 15 minutes
before it is due on a day it has not happened yet.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections.abc import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ira.devices.protocol import Event
from ira.learning.patterns import MIN_DAYS, Pattern, find_patterns, numbers_ok
from ira.learning.service import LearningService
from ira.learning.store import Learning, LearningError

log = logging.getLogger("ira.learning")

FADE_DAYS = 21
RECENT_DAYS = 5
NUDGE_MINUTES = 15
MAX_LINES = 8
MAX_CHARS = 600


def zone_for(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name) if name else _local_zone()
    except (ZoneInfoNotFoundError, ValueError):
        return _local_zone()


def _local_zone() -> ZoneInfo:
    from ira.channels.admin import local_timezone

    name = local_timezone()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def question(learning: Learning) -> tuple[str, str]:
    """How Ira asks, once: (title, text), with the numbers from the evidence."""
    if learning.status == "changed":
        return "This seems to have changed. Shall I remember the new times?", learning.text
    return "Shall I remember this?", learning.text


class Learner:
    def __init__(self, service: LearningService, *, clock: Callable[[], float] = time.time) -> None:
        self.service = service
        self.data = service.data
        self.clock = clock
        self._nudged: set[tuple[str, str]] = set()

    def zone(self, user_id: int) -> ZoneInfo:
        return zone_for(self.service.user_settings.get(user_id).timezone)

    # Learning.

    def patterns(self, user_id: int) -> list[Pattern]:
        prefs = self.service.user_settings.get(user_id)
        zone = self.zone(user_id)
        since = self.clock() - prefs.learning_days * 86400
        today = dt.datetime.fromtimestamp(self.clock(), zone).date()
        return find_patterns(self.data.observations(user_id, since=since), zone, today)

    async def run(self, user_id: int) -> list[Learning]:
        """Recompute this person's learnings, then ask about any that became ready."""
        if not self.service.user_settings.get(user_id).learning:
            return self.data.learnings(user_id)
        today = dt.datetime.fromtimestamp(self.clock(), self.zone(user_id)).date()
        found = {p.key: p for p in self.patterns(user_id)}
        for pattern in found.values():
            if not numbers_ok(pattern.text, pattern.evidence):  # never show an invented number
                log.error("a learning sentence did not match its evidence: %s", pattern.key)
                continue
            evidence = {**pattern.evidence, "observation_ids": pattern.observation_ids}
            existing = self.data.by_key(user_id, pattern.key)
            before = existing.status if existing else None
            if before in (None, "proposed", "ready"):
                status = "ready" if pattern.passes else "proposed"
            elif before == "faded":
                status = "ready" if pattern.passes else "faded"
            elif before == "asked":
                status = "asked"
            elif before == "active" and existing is not None and self._moved(existing, pattern):
                status = "changed"
            else:
                continue  # active and steady, or rejected: left as the person decided
            self.data.save(
                user_id,
                pattern.kind,
                pattern.key,
                pattern.text,
                evidence,
                pattern.confidence,
                status,
            )
        for learning in self.data.learnings(user_id, ("active",)):
            last = learning.evidence.get("last_day")
            if learning.key in found:
                last = found[learning.key].evidence.get("last_day", last)
            if last and (today - dt.date.fromisoformat(last)).days > FADE_DAYS:
                self.data.set_status(user_id, learning.id, "faded")
        await self.ask(user_id)
        return self.data.learnings(user_id)

    def _moved(self, active: Learning, pattern: Pattern) -> bool:
        """The last few days all fall outside the middle half the person approved."""
        if pattern.kind != "time" or "times" not in pattern.evidence:
            return False
        recent = pattern.evidence["times"][-RECENT_DAYS:]
        if len(recent) < RECENT_DAYS:
            return False
        low, high = active.evidence.get("q1"), active.evidence.get("q3")
        if not low or not high:
            return False
        return all(t < low or t > high for t in recent)

    async def ask(self, user_id: int) -> int:
        """Ask once about each learning that is ready or changed. Returns how many."""
        asked = 0
        for learning in self.data.learnings(user_id, ("ready", "changed")):
            if learning.asked_at is not None and learning.status != "changed":
                continue
            title, text = question(learning)
            self.data.set_status(user_id, learning.id, "asked", asked_at=self.clock())
            asked += 1
            if self.service.notify is not None:
                event = Event("learning_question", title, text, {"learning_id": learning.id})
                try:
                    await self.service.notify(user_id, event)
                except Exception:
                    log.exception("a learning question could not be sent")
        return asked

    # The person's answers.

    def approve(self, user_id: int, learning_id: str) -> Learning:
        learning = self._own(user_id, learning_id)
        if learning.status not in ("ready", "asked", "changed", "proposed", "faded", "rejected"):
            raise LearningError(f"this learning is already {learning.status}")
        if learning.status == "proposed" and learning.evidence.get("days", 0) < MIN_DAYS:
            raise LearningError("there is not enough evidence for this yet")
        self.data.set_status(user_id, learning_id, "active", decided_at=self.clock())
        return self._own(user_id, learning_id)

    def reject(self, user_id: int, learning_id: str) -> Learning:
        self._own(user_id, learning_id)
        self.data.set_status(user_id, learning_id, "rejected", decided_at=self.clock())
        return self._own(user_id, learning_id)

    def edit(self, user_id: int, learning_id: str, text: str) -> Learning:
        """Reword a learning. Its numbers must still come from its evidence."""
        learning = self._own(user_id, learning_id)
        text = " ".join(text.split())[:300]
        if not text:
            raise LearningError("say what Ira should remember")
        if not numbers_ok(text, learning.evidence):
            raise LearningError("a number in that sentence is not in the evidence")
        self.data.store.execute(
            "UPDATE learnings SET text = ?, updated_at = ? WHERE id = ?",
            (text, self.clock(), learning_id),
        )
        return self._own(user_id, learning_id)

    def forget(self, user_id: int, learning_id: str) -> int:
        """Forget a learning and the observations behind it. Returns how many were deleted."""
        learning = self._own(user_id, learning_id)
        ids = [int(i) for i in learning.evidence.get("observation_ids", [])]
        deleted = self.data.forget_observations(user_id, ids)
        self.data.forget_learning(user_id, learning_id)
        return deleted

    def _own(self, user_id: int, learning_id: str) -> Learning:
        learning = self.data.learning(user_id, learning_id)
        if learning is None:
            raise LearningError("no such learning")
        return learning

    # Use.

    def memory(self, user_id: int | None) -> list[str]:
        """The person's active learnings, for their prompt, within the budget."""
        if user_id is None or not self.service.user_settings.get(user_id).learning:
            return []
        lines: list[str] = []
        used = 0
        for learning in self.data.learnings(user_id, ("active",)):
            if len(lines) >= MAX_LINES or used + len(learning.text) > MAX_CHARS:
                break
            lines.append(learning.text)
            used += len(learning.text)
        return lines

    async def nudge(self, user_id: int) -> int:
        """Nudge 15 minutes before an active routine on a day it has not happened yet."""
        prefs = self.service.user_settings.get(user_id)
        if not (prefs.learning and prefs.nudges) or self.service.notify is None:
            return 0
        zone = self.zone(user_id)
        now = dt.datetime.fromtimestamp(self.clock(), zone)
        weekday = now.weekday() < 5
        sent = 0
        for learning in self.data.learnings(user_id, ("active",)):
            if learning.kind != "time" or not learning.key.startswith(("leave:", "arrive:")):
                continue
            if learning.key.endswith(":weekdays") != weekday:
                continue
            due = dt.datetime.combine(
                now.date(), dt.time.fromisoformat(learning.evidence["median"]), zone
            )
            minutes_left = (due - now).total_seconds() / 60
            day_key = (learning.id, now.date().isoformat())
            if not 0 <= minutes_left <= NUDGE_MINUTES or day_key in self._nudged:
                continue
            kind, place = learning.key.split(":")[:2]
            start = dt.datetime.combine(now.date(), dt.time(4, 0), zone).timestamp()
            happened = any(
                o["label"] == place
                for o in self.data.observations(user_id, since=start, kinds=(kind,))
            )
            if happened:
                continue
            self._nudged.add(day_key)
            verb = "leave" if kind == "leave" else "reach"
            title = (
                f"{now:%H:%M}: you usually {verb} {place} at about {learning.evidence['median']}"
            )
            await self.service.notify(user_id, Event("nudge", title, "", {}))
            sent += 1
        return sent
