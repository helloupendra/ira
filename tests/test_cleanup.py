"""What a long-running server keeps is bounded, and what a crash left behind is reset."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.models.fake import ScriptedProvider

from .conftest import make_runtime

pytestmark = pytest.mark.anyio


async def test_a_conversation_keeps_no_lock_once_its_turns_are_done():
    provider = ScriptedProvider(["one", "two", "three"])
    runtime = make_runtime(provider=provider)
    assistant = runtime.assistant
    await asyncio.gather(*(assistant.ask(f"q{n}", conversation_id=f"c{n % 2}") for n in range(3)))
    assert assistant._locks == {} and assistant._waiting == {}


def test_a_crash_leaves_no_live_calls_behind(tmp_path):
    runtime = make_runtime(data_dir=tmp_path)
    (tmp_path / "live-calls.json").write_text(json.dumps({"open": 2, "at": 1}))
    with TestClient(create_app(runtime, start_channels=False)):
        assert json.loads((tmp_path / "live-calls.json").read_text())["open"] == 0
