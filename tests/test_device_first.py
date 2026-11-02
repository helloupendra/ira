"""Asked from a device, Ira uses that device: its own tools first, and another device never
without the person's yes, always named (2 Nov 2026: "YouTube on karo" from the iPhone opened
YouTube on the Mac, silently)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ira.devices.hub import Connection
from ira.devices.protocol import DeviceTool
from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
pytestmark = pytest.mark.anyio


class Socket:
    async def send_text(self, data: str) -> None:
        pass

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        pass


def call(name: str, arguments: dict[str, Any]) -> ChatResponse:
    return ChatResponse(text="", tool_calls=[ToolCall("c1", name, json.dumps(arguments))])


OPEN = {"type": "object", "properties": {"name": {"type": "string"}}}
NOTHING: dict[str, Any] = {"type": "object", "properties": {}}
LINK = {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}


def world(script: list[Any], iphone_opens_links: bool = False):
    provider = ScriptedProvider(script)
    runtime = make_runtime(provider=provider)
    runtime.test_provider = provider
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    devices = runtime.hub.devices
    code, _ = devices.start_pairing(owner.id, "mac", "MacBook", ["apps"])
    _, mac = devices.redeem(code)
    code, _ = devices.start_pairing(owner.id, "ios", "My iPhone", ["apps", "contacts"])
    _, iphone = devices.redeem(code)
    mac_tools = {
        "screen_read": DeviceTool("screen_read", "Read the screen.", NOTHING, "apps", 0),
        "app_open": DeviceTool("app_open", "Open an app.", OPEN, "apps", 1),
        "url_open": DeviceTool("url_open", "Open a web page.", LINK, "apps", 2),
    }
    iphone_tools = {
        "contacts_lookup": DeviceTool("contacts_lookup", "Look up.", OPEN, "contacts", 0)
    }
    if iphone_opens_links:
        iphone_tools["url_open"] = DeviceTool("url_open", "Open a web page.", LINK, "apps", 2)
    runtime.hub.connections[mac.id] = Connection(mac, Socket(), mac_tools, 1.0)
    runtime.hub.connections[iphone.id] = Connection(iphone, Socket(), iphone_tools, 2.0)
    ran: list[tuple[int, str, dict[str, Any]]] = []

    async def fake_call(device_id: int, name: str, arguments: dict[str, Any]) -> Any:
        ran.append((device_id, name, arguments))
        return {"opened": True}

    runtime.hub.call = fake_call  # type: ignore[method-assign]
    return runtime, owner, mac, iphone, ran


async def turn(runtime: Any, owner: Any, text: str, device_id: int | None) -> list[dict[str, Any]]:
    return [
        event
        async for event in runtime.assistant.events(
            text, conversation_id="c1", channel="api", actor=owner.email, user_id=owner.id,
            device_id=device_id,
        )
    ]  # fmt: skip


async def test_from_the_iphone_the_mac_opens_nothing_without_a_yes_that_names_it():
    runtime, owner, mac, iphone, ran = world([call("app_open", {"name": "YouTube"}), "Shall I?"])
    events = await turn(runtime, owner, "youtube on karo", iphone.id)
    assert ran == []  # nothing was opened on the Mac
    proposed = [e for e in events if e["type"] == "action"]
    assert len(proposed) == 1
    summary = proposed[0]["action"]["summary"]
    assert "on MacBook" in summary and "not My iPhone" in summary and "YouTube" in summary
    assert proposed[0]["action"]["tier"] == 2  # a Tier 1 tool needs a yes from elsewhere
    tool = next(e for e in events if e["type"] == "tool")
    assert tool["device"].startswith("MacBook")  # the receipt names the device


async def test_ira_is_told_which_device_the_person_talks_from():
    runtime, owner, _, iphone, _ = world(["Theek hai."])
    await turn(runtime, owner, "hello", iphone.id)
    system = runtime.test_provider.calls[0]["messages"][0].content
    assert "talking to you from their device My iPhone" in system
    offered = {t["name"]: t for t in runtime.test_provider.calls[0]["tools"]}
    assert "not on My iPhone" in offered["app_open"]["description"]
    assert "they are asked for their yes" in offered["app_open"]["description"]
    assert (
        "This is the device the person is talking from" in offered["contacts_lookup"]["description"]
    )


async def test_from_the_web_the_mac_opens_an_app_at_once_as_before():
    runtime, owner, mac, _, ran = world([call("app_open", {"name": "YouTube"}), "Opened."])
    events = await turn(runtime, owner, "open youtube", None)
    assert ran == [(mac.id, "app_open", {"name": "YouTube"})]
    assert not [e for e in events if e["type"] == "action"]
    assert "talking to you from" not in runtime.test_provider.calls[0]["messages"][0].content


async def test_a_tool_both_devices_have_goes_to_the_one_asked_from():
    runtime, owner, mac, iphone, ran = world(
        [call("url_open", {"url": "https://www.youtube.com"}), "Yes or no?"],
        iphone_opens_links=True,
    )
    events = await turn(runtime, owner, "youtube kholo", iphone.id)
    schema = next(t for t in runtime.test_provider.calls[0]["tools"] if t["name"] == "url_open")
    assert "device" not in schema["parameters"].get("required", [])
    proposed = next(e for e in events if e["type"] == "action")["action"]
    # Tier 2 on the iPhone itself: an ordinary yes, with no "not" in it.
    assert runtime.guard.get(proposed["id"]).device_id == iphone.id
    assert "not My iPhone" not in proposed["summary"]
    assert ran == []
    assert next(e for e in events if e["type"] == "tool")["device"].startswith("My iPhone")
    _ = mac


async def test_from_the_phone_a_read_on_the_mac_runs_at_once():
    # 2 Nov 2026, from the Pixel: "you must talk from the MacBook", with the Mac connected.
    runtime, owner, mac, iphone, ran = world([call("screen_read", {}), "42 minutes."])
    events = await turn(runtime, owner, "मैकबुक पर टाइमर चेक करो", iphone.id)
    assert ran == [(mac.id, "screen_read", {})]
    assert not [e for e in events if e["type"] == "action"]


async def test_nothing_tells_the_model_to_refuse_another_device():
    runtime, owner, _, iphone, _ = world(["Theek hai."])
    await turn(runtime, owner, "hello", iphone.id)
    sent = runtime.test_provider.calls[0]
    system = sent["messages"][0].content
    offered = {t["name"]: t["description"] for t in sent["tools"]}
    assert "never tell them to talk from another device" in system
    assert "मैकबुक" in system
    assert "cannot do this" not in offered["screen_read"]
    assert "Use it when they name that device or when only it can answer" in offered["screen_read"]
    assert "they are asked" not in offered["screen_read"]


async def test_a_tool_of_a_device_gone_offline_says_so():
    runtime, owner, mac, iphone, _ = world([call("screen_read", {}), "Offline."])
    tools = [{"name": "screen_read", "skill": "apps", "tier": 0}]
    runtime.hub.devices.hello(mac.id, version="1", tools=tools)
    del runtime.hub.connections[mac.id]
    await turn(runtime, owner, "mac par kya hai", iphone.id)
    told = [m for m in runtime.test_provider.calls[1]["messages"] if m.role == "tool"][-1].content
    assert "MacBook" in told and "offline" in told.lower()
    assert "unknown tool" not in told


async def test_a_tool_nobody_has_is_still_unknown():
    runtime, owner, _, iphone, _ = world([call("made_up", {}), "Sorry."])
    await turn(runtime, owner, "do it", iphone.id)
    told = [m for m in runtime.test_provider.calls[1]["messages"] if m.role == "tool"][-1].content
    assert "unknown tool 'made_up'" in told
