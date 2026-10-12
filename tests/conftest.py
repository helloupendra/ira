"""Shared fixtures. Every test runs on fakes: no network, no keys, no cloud."""

from __future__ import annotations

import pytest

from ira.store import Store


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
