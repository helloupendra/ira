"""Skills a device has but the person has not switched on: Ira names them, never works around."""

from __future__ import annotations

import pytest

from ira.models.fake import ScriptedProvider

from .conftest import make_runtime

pytestmark = pytest.mark.anyio

PHONE_TOOLS = [
    {"name": "calls_recent", "skill": "calls", "tier": 0},
    {"name": "call_place", "skill": "calls", "tier": 2},
    {"name": "contacts_lookup", "skill": "contacts", "tier": 0},
    {"name": "sms_read", "skill": "messages", "tier": 0},
    {"name": "alarm_set", "tier": 1},  # no skill given: "alarm", from its name
]


async def test_a_phone_with_calls_off_is_named_and_not_worked_around():
    provider = ScriptedProvider(
        ["Pixel 7 mein Calls skill band hai: Your devices mein PIN se on karo."]
    )
    runtime = make_runtime(provider=provider)
    owner = runtime.accounts.create_user("owner@example.com", "a-long-password-here", "owner")
    devices = runtime.hub.devices
    code, _ = devices.start_pairing(owner.id, "android", "Pixel 7", ["contacts"])
    _, phone = devices.redeem(code)
    devices.hello(phone.id, version="1.0", tools=PHONE_TOOLS)  # what it said when it connected
    code, _ = devices.start_pairing(owner.id, "mac", "Studio Mac", [])
    devices.redeem(code)  # never connected: nothing known, so nothing listed

    assert runtime.switched_off(owner.id) == ["Pixel 7 (Android): alarm, calls, messages"]
    assert runtime.switched_off(None) == []

    reply = await runtime.assistant.ask(
        "aaj mere paas kitne missed calls aaye?", conversation_id="t", user_id=owner.id
    )
    system = provider.calls[0]["messages"][0].text
    assert "have NOT switched on" in system
    assert "  - Pixel 7 (Android): alarm, calls, messages\n" in system
    assert "under Your devices with their PIN" in system
    assert "contacts" not in system.split("have NOT switched on")[1].split("\n")[1]  # it is on
    assert "Calls skill band hai" in reply.text

    # With every skill on, the list is gone.
    devices.set_skills(phone.id, ["calls", "contacts", "messages", "alarm"])
    assert runtime.switched_off(owner.id) == []
    assert "have NOT switched on" not in runtime.assistant.system_prompt(owner.id)
