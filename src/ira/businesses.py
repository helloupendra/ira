"""Business profiles: each business a person works with, as they describe it.

What it is, the people there, the terms, and what Ira may do for it. The
person fills one in under "Your businesses", or tells Ira ("Sunrise pays net
30"), and Ira keeps it in mind in every conversation. "What Ira may do" is the
person's own rule for that business, which Ira follows; the tiers still ask
before anything changes. Profiles are the person's own words, so they are
trusted like anything else they type, and they are kept apart per person.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ira.store import Store
from ira.tools.personal import PersonalTool
from ira.tools.registry import ToolError

FIELDS = ("about", "people", "terms", "may_do")
LIMITS = {"name": 80, "about": 600, "people": 600, "terms": 600, "may_do": 400}
LABELS = {"about": "", "people": "People", "terms": "Terms", "may_do": "Ira may"}
MAX_BUSINESSES = 30
MAX_IN_PROMPT = 12
MAX_PROMPT_CHARS = 2400


class BusinessError(ValueError):
    pass


@dataclass
class Business:
    id: str
    name: str
    about: str
    people: str
    terms: str
    may_do: str
    updated_at: float

    def line(self) -> str:
        """One line for the prompt: "Sunrise Dental: a clinic. People: ... Ira may: ..."."""
        parts = [self.about] if self.about else []
        parts += [f"{LABELS[f]}: {getattr(self, f)}" for f in FIELDS[1:] if getattr(self, f)]
        return f"{self.name}: " + ". ".join(p.rstrip(".") for p in parts) if parts else self.name


def clean(value: Any, field: str) -> str:
    return " ".join(str(value or "").split())[: LIMITS[field]]


def _business(row: Any) -> Business:
    return Business(
        id=row["id"],
        name=row["name"],
        about=row["about"],
        people=row["people"],
        terms=row["terms"],
        may_do=row["may_do"],
        updated_at=row["updated_at"],
    )


class Businesses:
    def __init__(self, store: Store, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.clock = clock

    def list(self, user_id: int) -> list[Business]:
        # rowid breaks ties: the clock moves in steps on Windows, so rows added at once tie.
        rows = self.store.query(
            "SELECT * FROM businesses WHERE user_id = ? ORDER BY updated_at DESC, rowid DESC",
            (user_id,),
        )
        return [_business(r) for r in rows]

    def get(self, user_id: int, business_id: str) -> Business | None:
        row = self.store.one(
            "SELECT * FROM businesses WHERE user_id = ? AND id = ?", (user_id, business_id)
        )
        return _business(row) if row else None

    def by_name(self, user_id: int, name: str) -> Business | None:
        row = self.store.one(
            "SELECT * FROM businesses WHERE user_id = ? AND name = ? COLLATE NOCASE",
            (user_id, clean(name, "name")),
        )
        return _business(row) if row else None

    def add(self, user_id: int, name: str, **fields: Any) -> Business:
        name = clean(name, "name")
        if not name:
            raise BusinessError("give the business a name")
        if self.by_name(user_id, name) is not None:
            raise BusinessError(f"you already have {name}")
        count = self.store.one("SELECT COUNT(*) AS n FROM businesses WHERE user_id = ?", (user_id,))
        if count["n"] >= MAX_BUSINESSES:
            raise BusinessError(f"{MAX_BUSINESSES} businesses at most: remove one first")
        values = {f: clean(fields.get(f), f) for f in FIELDS}
        business_id = "biz_" + secrets.token_hex(6)
        now = self.clock()
        self.store.execute(
            "INSERT INTO businesses (id, user_id, name, about, people, terms, may_do, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (business_id, user_id, name, *(values[f] for f in FIELDS), now, now),
        )
        business = self.get(user_id, business_id)
        assert business is not None
        return business

    def change(self, user_id: int, business_id: str, **fields: Any) -> Business:
        business = self.get(user_id, business_id)
        if business is None:
            raise KeyError(business_id)
        values = {f: clean(v, f) for f, v in fields.items() if v is not None and f in LIMITS}
        if "name" in values:
            if not values["name"]:
                raise BusinessError("give the business a name")
            other = self.by_name(user_id, values["name"])
            if other is not None and other.id != business_id:
                raise BusinessError(f"you already have {values['name']}")
        if values:
            sets = ", ".join(f"{f} = ?" for f in values)
            self.store.execute(
                f"UPDATE businesses SET {sets}, updated_at = ? WHERE user_id = ? AND id = ?",
                (*values.values(), self.clock(), user_id, business_id),
            )
        changed = self.get(user_id, business_id)
        assert changed is not None
        return changed

    def remove(self, user_id: int, business_id: str) -> bool:
        cursor = self.store.execute(
            "DELETE FROM businesses WHERE user_id = ? AND id = ?", (user_id, business_id)
        )
        return cursor.rowcount == 1

    def lines(self, user_id: int | None) -> list[str]:
        """The person's businesses for their prompt, the latest changed first, within budget."""
        if user_id is None:
            return []
        lines: list[str] = []
        used = 0
        for business in self.list(user_id)[:MAX_IN_PROMPT]:
            line = business.line()
            if used + len(line) > MAX_PROMPT_CHARS:
                break
            lines.append(line)
            used += len(line)
        return lines

    def tools(self, user_id: int) -> list[PersonalTool]:
        """``remember_business``: Tier 1, the person told Ira; it is undoable on the page."""

        async def remember(arguments: dict[str, Any]) -> Any:
            name = clean(arguments.get("name"), "name")
            fields = {f: arguments.get(f) for f in FIELDS if arguments.get(f)}
            if not name or not fields:
                raise ToolError("say which business, and what to remember about it")
            try:
                business = self.by_name(user_id, name)
                if business is None:
                    business = self.add(user_id, name, **fields)
                else:
                    business = self.change(user_id, business.id, **fields)
            except BusinessError as exc:
                raise ToolError(str(exc)) from None
            return {"summary": f"I'll remember: {business.line()}"}

        return [
            PersonalTool(
                name="remember_business",
                description="Remember something about a business the person works with, when "
                "they tell you: what it is, its people, its terms, or what you may do for it. "
                "Each field you give replaces that field, so give its whole new text: what "
                "you knew plus the new fact.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "The business, as they name it."},
                        "about": {"type": "string", "description": "What it is, to them."},
                        "people": {"type": "string", "description": "Its people, and roles."},
                        "terms": {"type": "string", "description": "Rates, payment, deadlines."},
                        "may_do": {
                            "type": "string",
                            "description": "What the person lets you do for it, and not.",
                        },
                    },
                    "required": ["name"],
                },
                tier=1,
                source="ira",
                label="memory",
                run=remember,
                skill="memory",
            )
        ]
