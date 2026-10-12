"""Shared fixtures. Every test runs on fakes: no network, no keys, no cloud."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from ira.assistant import Assistant
from ira.conversations import Conversations
from ira.models.fake import ScriptedProvider
from ira.models.gateway import Gateway
from ira.store import Store
from ira.tools.actions import ActionGuard
from ira.tools.registry import ToolError, ToolRegistry

FAST_PIN_ITERATIONS = 1_000  # the real default is slow on purpose; tests need speed


class Clock:
    """A controllable time source for expiry and lock tests."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


class Ledger:
    """What the sample action tools did, so tests can count real executions."""

    def __init__(self) -> None:
        self.refunds: list[tuple[str, int]] = []


@pytest.fixture
def ledger() -> Ledger:
    return Ledger()


@pytest.fixture
def registry(ledger: Ledger) -> ToolRegistry:
    reg = ToolRegistry()

    @reg.tool
    def order_status(order_id: str) -> dict:
        """Look up an order."""
        return {"order_id": order_id, "status": "shipped"}

    def refund_summary(order_id: str, amount: int) -> str:
        if order_id == "missing":
            raise ToolError("there is no order 'missing'")
        return f"Refund {amount} on order {order_id}"

    @reg.action(summary=refund_summary)
    def refund(order_id: str, amount: int) -> dict:
        """Refund an order."""
        ledger.refunds.append((order_id, amount))
        return {"refunded": amount}

    return reg


def make_runtime(
    *,
    provider: Any = None,
    registry: ToolRegistry | None = None,
    store: Store | None = None,
    clock: Any = None,
) -> SimpleNamespace:
    store = store or Store(":memory:")
    registry = registry if registry is not None else ToolRegistry()
    gateway = Gateway(
        {"fake": provider or ScriptedProvider()}, {"default": ["fake:m"]}, store=store
    )
    guard_kwargs: dict[str, Any] = {"pin_iterations": FAST_PIN_ITERATIONS}
    if clock is not None:
        guard_kwargs["clock"] = clock
    guard = ActionGuard(store, registry, **guard_kwargs)
    conversations = Conversations(store)
    assistant = Assistant(gateway, registry, guard, store, conversations)
    return SimpleNamespace(
        store=store,
        registry=registry,
        gateway=gateway,
        guard=guard,
        conversations=conversations,
        assistant=assistant,
    )
