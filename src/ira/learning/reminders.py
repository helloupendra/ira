"""remind_me and my_reminders: a person's own reminders, at a time or at a named place.

``remind_me`` is Tier 1: small and undoable, so it runs at once and Ira says
what it set. A place reminder needs a place the person has named (a network
or a phone place); it fires when they reach or leave it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from ira.learning.service import LearningService
from ira.learning.store import clean_label
from ira.tools.personal import PersonalTool
from ira.tools.registry import ToolError

VERBS = {"arrive": "reaching", "leave": "leaving"}
REMIND_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "What to remind them of, in their words."},
        "at": {
            "type": "string",
            "description": "When, as a local date and time: 2026-10-23T09:00. Leave out for a "
            "place reminder.",
        },
        "when": {
            "type": "string",
            "enum": ["arrive", "leave"],
            "description": "For a place reminder: on reaching or on leaving the place.",
        },
        "place": {"type": "string", "description": "A place they named: Office, Home."},
    },
    "required": ["text"],
}


def known_places(service: LearningService, user_id: int) -> set[str]:
    places = {n["label"] for n in service.data.networks(user_id) if n["label"]}
    rows = service.data.store.query(
        "SELECT DISTINCT label FROM observations WHERE user_id = ? AND label IS NOT NULL",
        (user_id,),
    )
    return places | {r["label"] for r in rows}


def reminder_tools(service: LearningService, user_id: int, zone: dt.tzinfo) -> list[PersonalTool]:
    async def remind(arguments: dict[str, Any]) -> Any:
        text = " ".join(str(arguments.get("text") or "").split())[:200]
        if not text:
            raise ToolError("say what to remind them of")
        at, place, when = arguments.get("at"), arguments.get("place"), arguments.get("when")
        if at:
            try:
                moment = dt.datetime.fromisoformat(str(at))
            except ValueError:
                raise ToolError("give the time as 2026-10-23T09:00") from None
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=zone)
            now = dt.datetime.fromtimestamp(service.clock(), zone)
            if moment <= now:
                raise ToolError("that time has already passed")
            if moment - now > dt.timedelta(days=366):
                raise ToolError("reminders go at most a year ahead")
            reminder = service.data.add_reminder(
                user_id, text, trigger="time", due_at=moment.timestamp()
            )
            local = moment.astimezone(zone)
            return {
                "reminder": reminder["id"],
                "summary": f"Reminder set for {local:%A %d %B at %H:%M}: {text}",
            }
        if place and when in ("arrive", "leave"):
            label = clean_label(place)
            match = next(
                (p for p in known_places(service, user_id) if p.lower() == label.lower()), None
            )
            if match is None:
                raise ToolError(
                    f"I don't know a place called {label} yet. Name it on the What Ira knows "
                    "page, from your Mac's network or your phone."
                )
            reminder = service.data.add_reminder(user_id, text, trigger=when, place=match)
            verb = "reach" if when == "arrive" else "leave"
            return {
                "reminder": reminder["id"],
                "summary": f"I'll remind you when you {verb} {match}: {text}",
            }
        raise ToolError("give a time (at), or a place and when (arrive or leave)")

    async def listed(arguments: dict[str, Any]) -> Any:
        rows = service.data.reminders(user_id)
        return {
            "reminders": [
                {
                    "text": r["text"],
                    "when": (
                        dt.datetime.fromtimestamp(r["due_at"], zone).strftime("%a %d %b %H:%M")
                        if r["trigger"] == "time"
                        else f"on {VERBS[r['trigger']]} {r['place']}"
                    ),
                }
                for r in rows
            ]
        }

    return [
        PersonalTool(
            name="remind_me",
            description="Set a reminder for the person: at a time, or when they reach or leave "
            "a place they named.",
            parameters=REMIND_SCHEMA,
            tier=1,
            source="ira",
            label="reminders",
            run=remind,
            skill="reminders",
        ),
        PersonalTool(
            name="my_reminders",
            description="List the person's open reminders.",
            parameters={"type": "object", "properties": {}},
            tier=0,
            source="ira",
            label="reminders",
            run=listed,
            skill="reminders",
        ),
    ]
