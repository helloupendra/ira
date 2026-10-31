"""Taking in what is noticed about a person, only with their consent, and acting on it.

* Nothing is recorded unless the person switched learning on, and the source
  it came from (``mac``, ``phone``, ``conversation``, ``feedback``).
* The Mac reports lock, unlock, sleep, wake, its first activity of the day and
  its network, by a hash it makes itself. A network the person named turns
  into a place: reaching it is "arrive", moving off it is "leave".
* Reaching or leaving a place fires the person's reminders for that place.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ira.devices.protocol import Event
from ira.learning.store import (
    FINGERPRINT,
    MAC_KINDS,
    PLACE_KINDS,
    LearningError,
    LearningStore,
    clean_label,
)
from ira.store import Store
from ira.usersettings import UserSettings

log = logging.getLogger("ira.learning")

# A device's clock may be a little off; anything older than a day or in the future
# by more than five minutes is taken as "now".
CLOCK_SKEW = 300.0
MAX_AGE = 86400.0

Notify = Callable[[int, Event], Awaitable[Any]]


class LearningService:
    def __init__(
        self,
        store: Store,
        user_settings: UserSettings,
        *,
        notify: Notify | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.data = LearningStore(store, clock=clock)
        self.user_settings = user_settings
        self.notify = notify
        self.clock = clock
        self._mac_place: dict[int, str | None] = {}  # each person's last place by network

    def allowed(self, user_id: int, source: str) -> bool:
        """Learning is on for the person, and so is this source.

        A Mac's own switch is its ``routine`` skill, which the hub checks.
        """
        prefs = self.user_settings.get(user_id)
        return prefs.learning and (source == "mac" or source in prefs.learning_sources)

    def _when(self, at: Any) -> float:
        now = self.clock()
        number = isinstance(at, (int, float)) and not isinstance(at, bool)
        if number and now - MAX_AGE <= at <= now + CLOCK_SKEW:
            return float(min(at, now))
        return now

    async def record(
        self,
        user_id: int,
        kind: str,
        source: str,
        *,
        label: str | None = None,
        device_id: int | None = None,
        detail: dict[str, Any] | None = None,
        at: float | None = None,
    ) -> int | None:
        """Keep one observation, if the person allows this source; None if not."""
        if not self.allowed(user_id, source):
            return None
        days = self.user_settings.get(user_id).learning_days
        self.data.purge(user_id, days)
        observation = self.data.add(
            user_id, kind, source, at=at, label=label, device_id=device_id, detail=detail
        )
        if kind in PLACE_KINDS and label:
            await self._place_reminders(user_id, kind, label)
        return observation

    async def from_device(self, user_id: int, device_id: int, frame: dict[str, Any]) -> int | None:
        """An ``observe`` frame from a Mac or a Windows PC whose ``routine`` skill is on."""
        kind = frame.get("kind")
        if kind not in MAC_KINDS:
            raise LearningError(f"a computer observes {', '.join(MAC_KINDS)}")
        if not self.allowed(user_id, "mac"):
            return None
        fingerprint = frame.get("network")
        label = None
        if fingerprint is not None:
            if not isinstance(fingerprint, str) or not FINGERPRINT.fullmatch(fingerprint):
                raise LearningError("a network is sent as its hash only")
            label = self.data.network_seen(user_id, device_id, fingerprint)
        at = self._when(frame.get("at"))
        detail = {"network": fingerprint} if fingerprint else None
        observation = await self.record(
            user_id, kind, "mac", label=label, device_id=device_id, detail=detail, at=at
        )
        # Moving between named networks is reaching and leaving a place.
        if fingerprint is not None and kind in ("network", "wake", "unlock"):
            before = self._mac_place.get(user_id)
            if label != before:
                if before:
                    await self._place_reminders(user_id, "leave", before)
                if label:
                    await self._place_reminders(user_id, "arrive", label)
            self._mac_place[user_id] = label
        return observation

    async def from_phone(self, user_id: int, event: str, place: str) -> int | None:
        """A phone's place event (an iOS Shortcut): a place's name, never coordinates."""
        if event not in PLACE_KINDS:
            raise LearningError("event must be arrive or leave")
        return await self.record(user_id, event, "phone", label=clean_label(place))

    async def _place_reminders(self, user_id: int, trigger: str, place: str) -> None:
        for reminder in self.data.place_reminders(user_id, trigger, place):
            if self.data.finish_reminder(reminder["id"]) and self.notify is not None:
                verb = "reached" if trigger == "arrive" else "left"
                title = f"Reminder: {reminder['text']}"[:120]
                text = f"You {verb} {place}."
                try:
                    await self.notify(user_id, Event("reminder", title, text, {}))
                except Exception:
                    log.exception("a reminder could not be sent")

    async def fire_due(self) -> int:
        """Send every time reminder that is due. Returns how many."""
        sent = 0
        for reminder in self.data.due_reminders(self.clock()):
            if not self.data.finish_reminder(reminder["id"]):
                continue
            sent += 1
            if self.notify is not None:
                title = f"Reminder: {reminder['text']}"[:120]
                try:
                    await self.notify(reminder["user_id"], Event("reminder", title, "", {}))
                except Exception:
                    log.exception("a reminder could not be sent")
        return sent
