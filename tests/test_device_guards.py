"""What the code guarantees about devices, whatever the model would like (2 Nov 2026 scorecard):
the device named is the one used, a turn does not end on a promise, and think tags never show."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ira.devices.hub import Connection
from ira.devices.naming import Roster, named_devices
from ira.devices.protocol import DeviceTool
from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider
from ira.models.leaked import ThinkGate, strip_think
from ira.promises import PromiseGate, claims_done, promises

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
pytestmark = pytest.mark.anyio

MAC = Roster(1, "MacBook", "mac", True, ("screen",))
IPHONE = Roster(2, "My iPhone", "ios", True, ("calendar",))
PIXEL = Roster(3, "Pixel 7", "android", True, ("calls",))
ALL = [MAC, IPHONE, PIXEL]


@pytest.mark.parametrize(
    ("said", "ids"),
    [
        ("मैकबुक पर टाइमर चेक करो", {1}),
        ("मैक बुक पर टास्क प्लस", {1}),
        ("मेक बुक पर क्रोम के टैब बताओ", {1}),
        ("मैक पे सफारी में क्या है", {1}),
        ("mac par timer dekho", {1}),
        ("What's on my Mac's screen?", {1}),
        ("लैपटॉप पर क्या खुला है", {1}),
        ("मेरे कंप्यूटर की स्क्रीन", {1}),
        ("iPhone ki screen padho", {2}),
        ("आई फोन के रिमाइंडर", {2}),
        ("मेरा आईफोन कहाँ है", {2}),
        ("Read the screen of my Pixel", {3}),
        ("पिक्सल पर किसका कॉल", {3}),
        ("Pixel se sms bhejo", {3}),
        ("मोबाइल पर मिस्ड कॉल देखो", {2, 3}),
        ("phone par naya sms dekho", {2, 3}),
        ("Who called me on my phone?", {2, 3}),
        ("Open Safari", None),
        ("make a note for me", None),
        ("Avery ka phone number kya hai", None),
        ("एवरी का फोन नंबर बताओ", None),
        ("namaste", None),
    ],
)
def test_the_device_named_in_any_script(said: str, ids: set[int] | None):
    assert named_devices(said, ALL) == ids


def test_a_device_they_do_not_have_is_named_too():
    assert named_devices("iPhone ki screen padho", [MAC, PIXEL]) == set()
    assert named_devices("laptop par dekho", [IPHONE, PIXEL]) == set()
    assert named_devices("hello", [IPHONE, PIXEL]) is None


def test_a_device_by_its_own_name():
    studio = Roster(9, "Studio", "mac", True)
    assert named_devices("studio par dekho", [studio, PIXEL]) == {9}


def call(name: str, arguments: dict[str, Any] | None = None, text: str = "") -> ChatResponse:
    return ChatResponse(text=text, tool_calls=[ToolCall("c1", name, json.dumps(arguments or {}))])


NOTHING: dict[str, Any] = {"type": "object", "properties": {}}
MAC_TOOLS = {
    "screen_read": DeviceTool("screen_read", "Read the screen.", NOTHING, "screen", 0),
    "files_find": DeviceTool("files_find", "Find files.", NOTHING, "screen", 0),
    "file_read": DeviceTool("file_read", "Read a file.", NOTHING, "screen", 0),
    "app_open": DeviceTool("app_open", "Open an app.", NOTHING, "screen", 1),
}
PIXEL_TOOLS = {
    "timer_set": DeviceTool("timer_set", "Set a timer.", NOTHING, "calls", 1),
    "calendar_read": DeviceTool("calendar_read", "Read the calendar.", NOTHING, "calls", 0),
}


def world(script: list[Any], offline: tuple[str, ...] = ()):
    provider = ScriptedProvider(script)
    runtime = make_runtime(provider=provider)
    runtime.test_provider = provider
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    devices = runtime.hub.devices
    ids: dict[str, Any] = {}
    for name, kind, label, tools in (
        ("mac", "mac", "MacBook", MAC_TOOLS),
        ("pixel", "android", "Pixel 7", PIXEL_TOOLS),
    ):
        skills = sorted({t.skill for t in tools.values()})
        code, _ = devices.start_pairing(owner.id, kind, label, skills)
        _, device = devices.redeem(code)
        ids[name] = device
        if name not in offline:
            runtime.hub.connections[device.id] = Connection(device, Socket(), tools, 1.0)
    ran: list[tuple[int, str]] = []

    async def fake_call(device_id: int, name: str, arguments: dict[str, Any]) -> Any:
        ran.append((device_id, name))
        return {"summary": "Done."}

    runtime.hub.call = fake_call  # type: ignore[method-assign]
    return runtime, owner, ids, ran


class Socket:
    async def send_text(self, data: str) -> None:
        pass

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        pass


async def turn(runtime: Any, owner: Any, text: str, device: Any) -> list[dict[str, Any]]:
    return [
        event
        async for event in runtime.assistant.events(
            text, conversation_id="c1", channel="api", actor=owner.email, user_id=owner.id,
            device_id=device.id if device else None,
        )
    ]  # fmt: skip


def said(events: list[dict[str, Any]]) -> str:
    return "".join(e["text"] for e in events if e["type"] == "delta")


def offered(runtime: Any, call_number: int = 0) -> set[str]:
    return {t["name"] for t in runtime.test_provider.calls[call_number]["tools"]}


def last_result(runtime: Any) -> str:
    messages = runtime.test_provider.calls[-1]["messages"]
    return [m for m in messages if m.role == "tool"][-1].content


async def test_another_devices_tools_are_not_on_offer_when_one_is_named():
    runtime, owner, ids, ran = world(["Pixel ki screen nahi padh sakti."])
    await turn(runtime, owner, "Pixel ki screen padho", ids["mac"])
    assert "screen_read" not in offered(runtime)
    assert "calendar_read" in offered(runtime)
    assert ran == []


async def test_a_call_to_a_hidden_tool_runs_nothing_and_says_why():
    runtime, owner, ids, ran = world([call("screen_read"), "Nahi ho sakta."])
    await turn(runtime, owner, "Pixel ki screen padho", ids["mac"])
    assert ran == []
    told = last_result(runtime)
    assert "Not run" in told and "unknown tool" not in told


async def test_the_named_device_offline_uses_no_other_and_says_so():
    # 2 Nov 2026: with the Mac offline, "check the timer on the MacBook" set a timer on the Pixel.
    runtime, owner, ids, ran = world(["MacBook offline hai."], offline=("mac",))
    await turn(runtime, owner, "मैकबुक पर टाइमर चेक करो", ids["pixel"])
    assert "timer_set" not in offered(runtime)
    assert ran == []
    system = runtime.test_provider.calls[0]["messages"][0].content
    assert "MacBook (offline)" in system and "say that it is offline" in system


async def test_every_turn_lists_the_devices():
    runtime, owner, _, _ = world(["Namaste."], offline=("pixel",))
    await turn(runtime, owner, "namaste", None)
    system = runtime.test_provider.calls[0]["messages"][0].content
    assert "MacBook (connected): screen" in system and "Pixel 7 (offline)" in system


async def test_changing_something_elsewhere_is_not_on_offer_unnamed():
    runtime, owner, ids, ran = world([call("timer_set"), "Kis device par?", "Theek hai."])
    await turn(runtime, owner, "paanch minute ka timer", ids["mac"])
    assert "timer_set" not in offered(runtime)
    assert ran == []
    assert "did not name" in last_result(runtime)


async def test_an_open_approval_counts_as_naming_it():
    runtime, owner, ids, _ = world(["Ok."])
    runtime.approvals.open(owner.id, ids["mac"].id)
    await turn(runtime, owner, "button dabao", ids["pixel"])
    assert "app_open" in offered(runtime)


async def test_said_done_with_no_tool_gets_one_more_chance():
    # 2 Nov 2026: "Open Safari" -> "Done! I opened Safari", and nothing had run.
    runtime, owner, ids, ran = world(["Done! I opened Safari.", call("app_open"), "Khul gaya."])
    events = await turn(runtime, owner, "Open Safari", ids["mac"])
    assert ran == [(ids["mac"].id, "app_open")]
    assert "I opened Safari" not in said(events)  # never said, never spoken
    assert events[-1]["text"] == "Khul gaya."


async def test_saying_done_twice_ends_in_the_truth():
    runtime, owner, ids, ran = world(["Khol diya.", "Haan, khol diya."])
    events = await turn(runtime, owner, "Open Safari", ids["mac"])
    assert ran == []
    assert "khol diya" not in said(events).lower()
    assert events[-1]["text"] == "I haven't done anything yet. Could you ask again?"


async def test_a_promise_after_a_step_goes_on():
    runtime, owner, ids, ran = world(
        [call("files_find"), "Mil gayi. Let me read it.", call("file_read"), "18,250 baaki hai."]
    )
    events = await turn(runtime, owner, "invoice dhundo", ids["mac"])
    assert [name for _, name in ran] == ["files_find", "file_read"]
    assert events[-1]["text"] == "18,250 baaki hai."


async def test_a_lead_in_before_a_tool_is_still_said():
    runtime, owner, ids, ran = world([call("screen_read", text="Let me look."), "Timer chal raha."])
    events = await turn(runtime, owner, "screen padho", ids["mac"])
    assert ran and "Let me look." in said(events)


async def test_asking_which_device_is_answered_by_the_one_asked_from():
    runtime, owner, ids, ran = world(["किस डिवाइस पर देखूं?", call("calendar_read"), "Kuch nahi."])
    await turn(runtime, owner, "कल के कैलेंडर में क्या है", ids["pixel"])
    assert ran == [(ids["pixel"].id, "calendar_read")]


async def test_a_named_device_gets_its_tool_used_not_general_advice():
    runtime, owner, ids, ran = world(["Use Find My.", call("screen_read"), "Yeh hai."])
    await turn(runtime, owner, "mac par kya hai", ids["pixel"])
    assert ran == [(ids["mac"].id, "screen_read")]


async def test_two_things_asked_and_one_done_goes_on_and_is_said_once():
    runtime, owner, ids, ran = world(
        [call("files_find"), "Mil gayi file.", call("file_read"), "File 18,250 ki hai."]
    )
    events = await turn(runtime, owner, "file dhundo aur padho", ids["mac"])
    assert [name for _, name in ran] == ["files_find", "file_read"]
    assert said(events) == "File 18,250 ki hai."


async def test_a_plain_answer_with_no_device_named_passes_straight():
    runtime, owner, ids, _ = world(["Chaar."])
    events = await turn(runtime, owner, "do aur do kitna", ids["pixel"])
    assert said(events) == "Chaar." and len(runtime.test_provider.calls) == 1


def test_the_words_of_a_claim_and_a_promise():
    for words in ("Done! I opened Safari", "Safari खोल दिया", "मैंने किया", "bhej diya"):
        assert claims_done(words), words
    for words in ("Let me read it.", "main SMS bhejta hoon", "मैं देखता हूँ", "Ab main dekhti hoon"):
        assert promises(words), words
    for words in ("Yeh hai aapka calendar.", "दो और दो चार", "Thanks!"):
        assert not claims_done(words) and not promises(words), words


def test_the_gate_holds_only_from_a_doubtful_sentence():
    gate = PromiseGate()
    assert gate.feed("File mil gayi. ") == "File mil gayi."
    assert gate.feed("Let me read") == ""
    assert gate.feed(" it. More.") == ""
    assert gate.flush() == ""
    assert "Let me read it." in gate.take()
    held = PromiseGate(hold_all=True)
    assert held.feed("Anything. ") == "" and held.take() == "Anything. "
    plain = PromiseGate()
    assert plain.feed("no full stop") == "" and plain.flush() == "no full stop"


@pytest.mark.parametrize(
    ("text", "clean"),
    [
        ("<think>reasoning</think>Yeh raha.", "Yeh raha."),
        ("a draft </think> The answer.", "The answer."),
        ("The answer.<think>unfinished", "The answer."),
        ("Plain answer.", "Plain answer."),
    ],
)
def test_think_tags_never_stay(text: str, clean: str):
    assert strip_think(text) == clean


@pytest.mark.parametrize("cut", [1, 2, 3, 5, 8])
def test_think_tags_are_kept_out_however_the_pieces_are_cut(cut: int):
    text = "Pehle. <think>secret</think> Phir. </think> Ant."
    gate = ThinkGate()
    out = "".join(gate.feed(text[i : i + cut]) for i in range(0, len(text), cut)) + gate.flush()
    assert "think" not in out and "secret" not in out
    assert "Pehle." in out and "Ant." in out


async def test_think_tags_never_reach_the_person_streamed_or_not():
    runtime, owner, _, _ = world(["<think>mull it over</think>Namaste."])
    events = await turn(runtime, owner, "namaste", None)
    assert said(events) == "Namaste." and events[-1]["text"] == "Namaste."
    runtime, owner, _, _ = world(["Namaste. </think>Sach mein namaste."])
    reply = await runtime.assistant.ask("namaste", conversation_id="c2", user_id=owner.id)
    assert reply.text == "Sach mein namaste."
