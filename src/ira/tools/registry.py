"""Registering tools: functions Ira may call to read data or propose actions.

    from ira import tool, action

    @tool
    def clinic_hours() -> dict:
        "Opening hours for each day of the week."
        ...

    @action(summary="Book {name} at {slot}")
    def book_appointment(name: str, slot: str) -> dict:
        "Book an appointment. Runs only after the owner confirms with the PIN."
        ...

Arguments come from the function signature (use ``Annotated[..., Field(...)]``
for descriptions), or from a single pydantic model parameter. Either way the
JSON schema the model sees and the validation Ira applies are the same object.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, get_type_hints

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

ToolKind = Literal["read", "action"]
NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


class ToolError(Exception):
    """Raise from a tool to send a plain message back to the model and the user."""


@dataclass
class ToolContext:
    """Handed to a tool module's optional ``setup(ctx)`` and ``seed(ctx)`` hooks."""

    data_dir: Path
    config_dir: Path = field(default_factory=Path.cwd)


class _ArgsBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]
    args_model: type[BaseModel]
    kind: ToolKind
    summary: str | Callable[..., str] | None = None
    takes_model: bool = False  # fn(args) instead of fn(**args)

    def schema(self) -> dict[str, Any]:
        """Provider-neutral spec: name, description, JSON schema of the arguments."""
        parameters = _clean_schema(self.args_model.model_json_schema())
        parameters.setdefault("properties", {})
        parameters["type"] = "object"
        return {"name": self.name, "description": self.description, "parameters": parameters}

    def validate(self, arguments: dict[str, Any]) -> BaseModel:
        return self.args_model.model_validate(arguments)

    def call_args(self, args: BaseModel) -> tuple[tuple[Any, ...], dict[str, Any]]:
        if self.takes_model:
            return (args,), {}
        return (), {name: getattr(args, name) for name in type(args).model_fields}

    def describe(self, args: BaseModel) -> str:
        """The human summary of a proposed action, with its arguments filled in."""
        if callable(self.summary):
            positional, keywords = self.call_args(args)
            return str(self.summary(*positional, **keywords))
        values = args.model_dump()
        if isinstance(self.summary, str):
            return self.summary.format(**values)
        shown = ", ".join(f"{k}={v!r}" for k, v in values.items())
        return f"{self.name}({shown})"


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Drop pydantic's auto-generated titles; they only cost tokens."""
    if isinstance(schema, dict):
        return {
            k: _clean_schema(v)
            for k, v in schema.items()
            if not (k == "title" and isinstance(v, str))
        }
    if isinstance(schema, list):
        return [_clean_schema(v) for v in schema]
    return schema


def _first_paragraph(doc: str | None) -> str:
    if not doc:
        return ""
    return inspect.cleandoc(doc).split("\n\n")[0].replace("\n", " ").strip()


def _args_model(fn: Callable[..., Any], name: str) -> tuple[type[BaseModel], bool]:
    signature = inspect.signature(fn)
    try:
        hints = get_type_hints(fn, include_extras=True)
    except NameError as exc:
        raise TypeError(
            f"tool '{name}': cannot resolve the type hints ({exc}); "
            "define argument types at module level"
        ) from None
    params = [
        p
        for p in signature.parameters.values()
        if p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    ]
    if len(params) == 1:
        hint = hints.get(params[0].name)
        if inspect.isclass(hint) and issubclass(hint, BaseModel):
            return hint, True
    fields: dict[str, Any] = {}
    for param in params:
        if param.name not in hints:
            raise TypeError(f"tool '{name}': parameter '{param.name}' needs a type annotation")
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param.name] = (hints[param.name], default)
    model_name = "".join(part.title() for part in name.split("_")) + "Args"
    return create_model(model_name, __base__=_ArgsBase, **fields), False


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._disabled: set[str] = set()

    def register(
        self,
        fn: Callable[..., Any],
        *,
        kind: ToolKind,
        name: str | None = None,
        description: str | None = None,
        summary: str | Callable[..., str] | None = None,
    ) -> Tool:
        tool_name = name or fn.__name__
        if not NAME_PATTERN.fullmatch(tool_name):
            raise ValueError(f"tool name '{tool_name}' must match {NAME_PATTERN.pattern}")
        if tool_name in self._tools:
            raise ValueError(f"a tool named '{tool_name}' is already registered")
        text = description or _first_paragraph(fn.__doc__)
        if not text:
            raise ValueError(f"tool '{tool_name}' needs a description or a docstring")
        args_model, takes_model = _args_model(fn, tool_name)
        registered = Tool(
            name=tool_name,
            description=text,
            fn=fn,
            args_model=args_model,
            kind=kind,
            summary=summary,
            takes_model=takes_model,
        )
        self._tools[tool_name] = registered
        return registered

    def tool(
        self,
        fn: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> Any:
        """Register a read tool: Ira may call it freely to look things up."""

        def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
            self.register(func, kind="read", name=name, description=description)
            return func

        return decorate(fn) if fn is not None else decorate

    def action(
        self,
        fn: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
        summary: str | Callable[..., str] | None = None,
    ) -> Any:
        """Register an action tool: calling it only proposes; the owner confirms with a PIN.

        ``summary`` is a format string over the arguments, or a function taking
        the same arguments as the tool. A summary function may look things up
        and raise ``ToolError`` to refuse the proposal (e.g. unknown record).
        """

        def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
            self.register(func, kind="action", name=name, description=description, summary=summary)
            return func

        return decorate(fn) if fn is not None else decorate

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    # Switching tools off: a switched-off tool stays registered, but the model
    # does not see it and a pending action for it does not run.

    def is_enabled(self, name: str) -> bool:
        return name in self._tools and name not in self._disabled

    def set_enabled(self, name: str, enabled: bool) -> None:
        if name not in self._tools:
            raise KeyError(name)
        if enabled:
            self._disabled.discard(name)
        else:
            self._disabled.add(name)

    def disabled(self) -> set[str]:
        return set(self._disabled)

    def schemas(self) -> list[dict[str, Any]]:
        """Schemas of the tools the model may call (switched-off tools are left out)."""
        return [t.schema() for t in self._tools.values() if t.name not in self._disabled]

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools


def validation_message(error: ValidationError) -> str:
    parts = []
    for item in error.errors()[:5]:
        where = ".".join(str(p) for p in item.get("loc", ())) or "arguments"
        parts.append(f"{where}: {item.get('msg', 'invalid')}")
    return "; ".join(parts)


default_registry = ToolRegistry()
tool = default_registry.tool
action = default_registry.action
