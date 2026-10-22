"""Background work for learning: due reminders and nudges every minute, the learner nightly."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from collections.abc import Callable

from ira.learning.learner import Learner

log = logging.getLogger("ira.learning")

TICK_SECONDS = 60.0
NIGHTLY_HOUR = 3  # the learner runs once a night, after 03:00 in each person's time zone


class LearningScheduler:
    def __init__(self, learner: Learner, *, clock: Callable[[], float] = time.time) -> None:
        self.learner = learner
        self.clock = clock
        self._ran: dict[int, str] = {}  # person -> the night the learner last ran for them

    def people(self) -> list[int]:
        rows = self.learner.data.store.query(
            "SELECT s.user_id FROM user_settings s JOIN users u ON u.id = s.user_id "
            "WHERE s.key = 'learning' AND s.value = 'true' AND u.disabled_at IS NULL"
        )
        return [int(r["user_id"]) for r in rows]

    async def tick(self) -> None:
        await self.learner.service.fire_due()
        for user_id in self.people():
            try:
                await self.learner.nudge(user_id)
                now = dt.datetime.fromtimestamp(self.clock(), self.learner.zone(user_id))
                night = now.date().isoformat()
                if now.hour >= NIGHTLY_HOUR and self._ran.get(user_id) != night:
                    self._ran[user_id] = night
                    await self.learner.run(user_id)
            except Exception:
                log.exception("learning for person %s failed", user_id)

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("the learning tick failed")
            await asyncio.sleep(TICK_SECONDS)
