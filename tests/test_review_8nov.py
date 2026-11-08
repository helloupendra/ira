"""Findings of the review of 8 Nov 2026 that a test can hold: half-made streams, a server's own
read-only hint, a PIN inside a sentence, observations of people who stopped using Ira, and a
device call stuck in its send."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from ira.connectors.mcp import default_tier
from ira.devices.hub import Connection, DeviceHub
from ira.devices.protocol import DeviceTool
from ira.models.anthropic import AnthropicProvider
from ira.models.base import Message, ProviderError, StreamDone
from ira.models.fake import ScriptedProvider
from ira.models.http import HeaderKeyAuth, HttpClient
from ira.models.openai_compat import OpenAICompatProvider
from ira.security import holds_a_pin
from ira.tools.registry import ToolTimeout

from .conftest import make_runtime
from .test_providers import TOOLS, client, sse

pytestmark = pytest.mark.anyio

TOOL_HEADER = {
    "choices": [
        {"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "find_slots"}}]}}
    ]
}


def answering(body: bytes) -> httpx.AsyncClient:
    return client(lambda request: httpx.Response(200, content=body))


async def drain(provider) -> list:
    return [
        e
        async for e in provider.stream(
            "m", [Message(role="user", content="hi")], TOOLS, max_tokens=50, timeout=5
        )
    ]


async def test_a_stream_cut_after_a_tool_header_never_makes_a_call():
    provider = OpenAICompatProvider(
        HttpClient("https://llm.example.com/v1", client=answering(sse(TOOL_HEADER)))
    )
    with pytest.raises(ProviderError):
        await drain(provider)


async def test_words_cut_short_stand_marked_as_cut():
    body = sse({"choices": [{"delta": {"content": "Your appointment is on"}}]})
    provider = OpenAICompatProvider(
        HttpClient("https://llm.example.com/v1", client=answering(body))
    )
    done = (await drain(provider))[-1]
    assert isinstance(done, StreamDone) and done.response.stop_reason == "incomplete"
    empty = OpenAICompatProvider(HttpClient("https://llm.example.com/v1", client=answering(b"")))
    with pytest.raises(ProviderError):  # nothing at all: another model may answer
        await drain(empty)


async def test_an_anthropic_stream_cut_inside_a_tool_use_never_makes_a_call():
    body = sse(
        {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "tu_1", "name": "find_slots"},
        },
    )
    http = HttpClient(
        "https://api.example.com", HeaderKeyAuth("test-key-123"), client=answering(body)
    )
    with pytest.raises(ProviderError):
        await drain(AnthropicProvider(http))


def test_destructive_words_outrank_a_read_only_hint():
    assert (
        default_tier("execute", "Deletes the records you name, for good.", {"readOnlyHint": True})
        == 3
    )
    assert default_tier("list_items", "Lists the items in a folder.", {"readOnlyHint": True}) == 0


@pytest.mark.parametrize(
    ("text", "pin"),
    [
        ("Use my PIN 4321 to approve this", True),
        ("mera PIN 4321 hai, approve kar do", True),
        ("पिन ४३२१ है", True),
        ("mera pin code 110001 hai", False),
        ("pincode 110001", False),
        ("PIN kya hota hai?", False),
        ("Order 4471 is ready", False),
    ],
)
def test_a_pin_inside_a_sentence(text, pin):
    assert holds_a_pin(text) is pin


async def test_a_pin_inside_a_sentence_reaches_no_model_and_no_history():
    provider = ScriptedProvider(["Approved."])
    runtime = make_runtime(provider=provider)
    events = [
        e
        async for e in runtime.assistant.events(
            "Use my PIN 4321 to approve this", conversation_id="p"
        )
    ]
    assert provider.calls == []
    assert "never read PINs" in events[-1]["text"]
    assert all("4321" not in (m.content or "") for m in runtime.assistant.history("p"))


def test_old_observations_go_for_people_who_stopped_using_ira():
    runtime = make_runtime(provider=ScriptedProvider([]))
    user = runtime.accounts.create_first_owner("owner@example.com", "a-long-password-here")
    learning = runtime.learning
    assert learning is not None
    old = time.time() - 400 * 86400
    learning.data.add(user.id, "unlock", "mac", at=old)
    learning.data.add(user.id, "unlock", "mac", at=time.time() - 3600)
    assert learning.purge_all() == 1
    assert learning.purge_all() == 0


class StuckSocket:
    async def send_text(self, data: str) -> None:
        await asyncio.sleep(30)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        pass


async def test_a_device_call_stuck_in_its_send_still_ends_on_time():
    runtime = make_runtime(provider=ScriptedProvider([]))
    owner = runtime.accounts.create_first_owner("owner@example.com", "a-long-password-here")
    hub: DeviceHub = runtime.hub
    code, _ = hub.devices.start_pairing(owner.id, "mac", "mac", ["screen"])
    _, device = hub.devices.redeem(code)
    tool = DeviceTool("screen_read", "Read the screen.", {"type": "object"}, "screen", 0)
    hub.connections[device.id] = Connection(device, StuckSocket(), {"screen_read": tool}, 1.0)
    began = time.monotonic()
    with pytest.raises(ToolTimeout):
        await hub.call(device.id, "screen_read", {}, timeout=0.3)
    assert time.monotonic() - began < 3
    assert hub.connections[device.id].pending == {}  # the slot is free again
