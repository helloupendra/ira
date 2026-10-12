from __future__ import annotations

from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, Field, ValidationError

from ira.tools.registry import ToolRegistry


def test_schema_comes_from_the_signature():
    reg = ToolRegistry()

    @reg.tool
    def find_slots(
        date: Annotated[str, Field(description="YYYY-MM-DD")],
        length: Literal[30, 60] = 30,
    ) -> dict:
        """Free appointment slots on one day.

        Longer explanation that should not reach the model.
        """
        return {}

    spec = reg.get("find_slots").schema()
    assert spec["name"] == "find_slots"
    assert spec["description"] == "Free appointment slots on one day."
    params = spec["parameters"]
    assert params["type"] == "object"
    assert params["required"] == ["date"]
    assert params["properties"]["date"] == {"type": "string", "description": "YYYY-MM-DD"}
    assert params["properties"]["length"]["enum"] == [30, 60]
    assert params["additionalProperties"] is False
    assert "title" not in params and "title" not in params["properties"]["date"]


def test_tool_without_arguments_has_an_empty_object_schema():
    reg = ToolRegistry()

    @reg.tool
    def clinic_hours() -> dict:
        """Opening hours."""
        return {}

    params = reg.get("clinic_hours").schema()["parameters"]
    assert params["type"] == "object"
    assert params["properties"] == {}


class Booking(BaseModel):
    name: str = Field(min_length=2)
    slot: str


def test_a_pydantic_model_parameter_is_used_as_is():
    reg = ToolRegistry()

    @reg.action(summary="Book {name} at {slot}")
    def book(args: Booking) -> dict:
        """Book a slot."""
        return {"booked": args.name}

    tool = reg.get("book")
    assert tool.kind == "action"
    assert tool.schema()["parameters"]["required"] == ["name", "slot"]
    args = tool.validate({"name": "Avery Example", "slot": "2026-10-14 09:30"})
    assert tool.describe(args) == "Book Avery Example at 2026-10-14 09:30"
    positional, keywords = tool.call_args(args)
    assert tool.fn(*positional, **keywords) == {"booked": "Avery Example"}


def test_validation_rejects_wrong_types_and_unknown_arguments():
    reg = ToolRegistry()

    @reg.tool
    def cancel(id: int) -> dict:
        """Cancel."""
        return {}

    tool = reg.get("cancel")
    assert tool.validate({"id": "7"}).id == 7  # pydantic's lax mode coerces numeric strings
    with pytest.raises(ValidationError):
        tool.validate({"id": "seven"})
    with pytest.raises(ValidationError):
        tool.validate({"id": 1, "force": True})


def test_registration_errors_are_clear():
    reg = ToolRegistry()

    with pytest.raises(TypeError, match="needs a type annotation"):

        @reg.tool
        def untyped(x) -> dict:  # type: ignore[no-untyped-def]
            """No annotation."""
            return {}

    with pytest.raises(ValueError, match="needs a description"):

        @reg.tool
        def silent(x: int) -> dict:
            return {}

    with pytest.raises(ValueError, match="must match"):
        reg.register(lambda: None, kind="read", name="has spaces", description="x")

    @reg.tool
    def once() -> dict:
        """Once."""
        return {}

    with pytest.raises(ValueError, match="already registered"):
        reg.register(once, kind="read")


def test_schemas_list_every_tool_in_registration_order():
    reg = ToolRegistry()

    @reg.tool
    def a() -> dict:
        """A."""
        return {}

    @reg.action
    def b() -> dict:
        """B."""
        return {}

    assert [s["name"] for s in reg.schemas()] == ["a", "b"]
    assert [t.kind for t in reg] == ["read", "action"]


def test_a_switched_off_tool_stays_registered_but_the_model_cannot_see_it():
    reg = ToolRegistry()

    @reg.tool
    def a() -> dict:
        """A."""
        return {}

    @reg.tool
    def b() -> dict:
        """B."""
        return {}

    reg.set_enabled("a", False)
    assert [s["name"] for s in reg.schemas()] == ["b"]
    assert "a" in reg and not reg.is_enabled("a") and reg.disabled() == {"a"}
    reg.set_enabled("a", True)
    assert [s["name"] for s in reg.schemas()] == ["a", "b"]
    assert not reg.is_enabled("missing")
    with pytest.raises(KeyError):
        reg.set_enabled("missing", False)
