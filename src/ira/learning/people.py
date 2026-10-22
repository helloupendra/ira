"""People in a person's life, as they told Ira: "Rahul mera CA hai".

``remember_person`` and ``forget_person`` are Tier 1: the person asked, it is
small and undoable, Ira does it at once and says so. Each is a learning of
kind ``person``, active at once (the person said it; there is nothing to
prove), shown and forgettable on "What Ira knows about you", and given to
the model with the person's other memory. It needs no learning switch:
being told to remember is the consent.
"""

from __future__ import annotations

import re
from typing import Any

from ira.learning.store import LearningStore
from ira.tools.personal import PersonalTool
from ira.tools.registry import ToolError

MAX_PEOPLE = 20  # in the prompt
MAX_PEOPLE_CHARS = 1200


def person_key(name: str) -> str:
    return "person:" + " ".join(re.sub(r"[^\w\s]", " ", name.lower()).split())


def _clean(text: Any, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def people_lines(data: LearningStore, user_id: int) -> list[str]:
    lines: list[str] = []
    used = 0
    for learning in data.learnings(user_id, ("active",)):
        if learning.kind != "person":
            continue
        if len(lines) >= MAX_PEOPLE or used + len(learning.text) > MAX_PEOPLE_CHARS:
            break
        lines.append(learning.text)
        used += len(learning.text)
    return lines


def people_tools(data: LearningStore, user_id: int) -> list[PersonalTool]:
    async def remember(arguments: dict[str, Any]) -> Any:
        name = _clean(arguments.get("name"), 60)
        about = _clean(arguments.get("about"), 200)
        if not name or not about:
            raise ToolError("say who it is and who they are to the person")
        key = person_key(name)
        if key == "person:":
            raise ToolError("that name has no letters")
        text = f"{name}: {about}"
        data.save(user_id, "person", key, text, {"told": True}, 1.0, "active")
        return {"summary": f"I'll remember: {text}"}

    async def forget(arguments: dict[str, Any]) -> Any:
        name = _clean(arguments.get("name"), 60)
        learning = data.by_key(user_id, person_key(name)) if name else None
        if learning is None or learning.kind != "person":
            return {"summary": f"I had nothing saved about {name or 'them'}."}
        data.forget_learning(user_id, learning.id)
        return {"summary": f"Forgotten: {learning.text}"}

    return [
        PersonalTool(
            name="remember_person",
            description="Remember who someone is to the person, when they tell you: their "
            "role, relation or how they know them ('Rahul Sharma is my CA'). Use the name as "
            "they say it.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The name, as they say it."},
                    "about": {
                        "type": "string",
                        "description": "Who they are to the person, in a few words.",
                    },
                },
                "required": ["name", "about"],
            },
            tier=1,
            source="ira",
            label="memory",
            run=remember,
            skill="memory",
        ),
        PersonalTool(
            name="forget_person",
            description="Forget what you were told about someone, when the person asks.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            tier=1,
            source="ira",
            label="memory",
            run=forget,
            skill="memory",
        ),
    ]
