"""What the code guarantees about devices, whatever the model would like (2 Nov 2026 scorecard):
the device named is the one used, a turn does not end on a promise, and think tags never show."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ira.assistant import NOT_DONE
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
    studio_mac = Roster(9, "Studio Mac", "mac", True)
    assert named_devices("What's open on Studio Mac?", [studio_mac, PIXEL]) == {9}


@pytest.mark.parametrize(
    ("said", "ids"),
    [
        # A plain word for a computer names it only as a place.
        ("Remind me to charge my laptop", None),
        ("Call the computer repair shop", None),
        ("buy a new laptop bag", None),
        ("What's open on my laptop?", {1}),
        ("laptop pe kya khula hai", {1}),
        ("Read my laptop's screen", {1}),
        ("computer se file bhejo", {1}),
        ("laptop ka number kya hai", None),
    ],
)
def test_a_plain_word_names_a_device_only_as_a_place(said: str, ids: set[int] | None):
    assert named_devices(said, ALL) == ids


def test_windows_is_also_what_a_room_has():
    office = Roster(7, "Office PC", "windows", True, ("screen",))
    assert named_devices("close the windows when it rains", [office, PIXEL]) is None
    assert named_devices("windows par kya chal raha hai", [office, PIXEL]) == {7}
    assert named_devices("What's on the office pc?", [office, PIXEL]) == {7}


def test_the_owners_name_in_a_label_is_a_person_not_the_device():
    # "Text Upendra bhai" is about a person: the Pixel that sends texts stays on offer.
    phone = Roster(5, "Upendra's iPhone", "ios", True, ("calendar",))
    assert named_devices("Text Upendra bhai that I'm late", [phone, PIXEL]) is None
    assert named_devices("Upendra’s iPhone ki screen padho", [phone, PIXEL]) == {5}
    # A model word is not a name: "the air conditioner" is not the MacBook Air.
    air = Roster(6, "MacBook Air", "mac", True)
    assert named_devices("turn on the air conditioner", [air, PIXEL]) is None


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
    done = call("finish_turn", {"say": "File 18,250 ki hai."})
    runtime, owner, ids, ran = world(
        [call("files_find"), "Mil gayi file.", call("file_read"), "Padh li.", done]
    )
    events = await turn(runtime, owner, "file dhundo aur padho", ids["mac"])
    assert [name for _, name in ran] == ["files_find", "file_read"]
    assert said(events) == "File 18,250 ki hai."
    assert runtime.test_provider.forced == ["required", "required"]


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


@pytest.mark.parametrize(
    "words",
    [
        "Done.",
        "All done!",
        "Ok, done. Safari is open.",
        "I've opened Safari.",
        "I just sent it to Avery.",
        "Opened Safari for you.",
        "Your alarm has been set for 6.",
        "It's done.",
        "I read your screen: the timer says 4 minutes.",
        "Alarm set ho gaya.",
        "Maine message bhej diya.",
        "मैंने मैसेज भेज दिया।",
        "Main ne bhej diya.",
    ],
)
def test_her_own_word_that_she_did_something_is_a_claim(words: str):
    assert claims_done(words), words


@pytest.mark.parametrize(
    "words",
    [
        # News and history: something happened, not something she did.
        "The shop opened in 1990.",
        "Sunrise Dental opened a new clinic last year.",
        "The report is done by Friday, says the email.",
        # The past it tells of.
        "Haan, woh meeting cancel ho gaya tha.",
        "मीटिंग कैंसल हो गई थी।",
        # What another did.
        "Avery ne bhej diya.",
        "Aapne kal hi bhej diya.",
        "एवरी ने मैसेज भेज दिया।",
        "He opened the door.",
        # A question, and not done.
        "Kya ho gaya?",
        "I haven't opened it yet.",
        "I read that the shop closes at 9.",
    ],
)
def test_news_the_past_and_others_doings_are_no_claim(words: str):
    assert not claims_done(words), words


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


async def test_a_promise_round_must_call_a_tool_and_the_escape_is_offered():
    runtime, owner, ids, ran = world(["Main dekhti hoon.", call("screen_read"), "Timer chal raha."])
    await turn(runtime, owner, "screen padho", ids["mac"])
    assert ran == [(ids["mac"].id, "screen_read")]
    assert runtime.test_provider.forced == ["required"]
    tools = {t["name"] for t in runtime.test_provider.calls[1]["tools"]}
    assert "finish_turn" in tools  # only there
    assert "finish_turn" not in {t["name"] for t in runtime.test_provider.calls[0]["tools"]}


async def test_finishing_in_words_is_the_answer_but_a_promise_in_them_is_not():
    done = call("finish_turn", {"say": "Yeh yahan nahi ho sakta."})
    runtime, owner, ids, ran = world(["Main dekhti hoon.", done])
    events = await turn(runtime, owner, "screen padho", ids["mac"])
    assert ran == [] and events[-1]["text"] == "Yeh yahan nahi ho sakta."
    again = call("finish_turn", {"say": "Main abhi dekhti hoon."})
    runtime, owner, ids, ran = world(["Main dekhti hoon.", again])
    events = await turn(runtime, owner, "screen padho", ids["mac"])
    assert events[-1]["text"] in NOT_DONE.values()


async def test_what_was_found_stands_when_only_its_closing_promise_is_empty():
    closing = "Timer 01:23 hai. Main aur dekhti hoon."
    runtime, owner, ids, _ = world([call("screen_read"), closing, closing])
    events = await turn(runtime, owner, "screen padho", ids["mac"])
    assert events[-1]["text"] == "Timer 01:23 hai."


async def test_a_model_that_cannot_be_forced_still_gets_the_rule():
    from ira.models.base import ProviderError

    runtime, owner, ids, ran = world(["Main dekhti hoon.", call("screen_read"), "Yeh hai."])
    provider = runtime.test_provider
    real = provider.chat

    async def refuses(model: str, messages: Any, tools: Any, **options: Any) -> Any:
        if options.get("tool_choice"):
            raise ProviderError("tool_choice is not supported", kind="bad_request")
        return await real(model, messages, tools, **options)

    provider.chat = refuses
    await turn(runtime, owner, "screen padho", ids["mac"])
    assert ran == [(ids["mac"].id, "screen_read")]


async def test_a_yes_asked_in_words_becomes_the_real_card():
    runtime, owner, ids, ran = world(["Avery ko bhejun? Haan bolo.", call("app_open"), "Dekh lo."])
    events = await turn(runtime, owner, "mac par safari kholo", ids["pixel"])
    assert [e for e in events if e["type"] == "action"]
    assert ran == []
    assert "Haan bolo" not in said(events)


def test_first_person_now_and_next_are_promises_and_can_is_not():
    for words in (
        "Ab invoice wala tab aage laata hoon.",
        "main MacBook pe YouTube khool raha hoon",
        "मैं आपके iPhone पर Avery का नंबर ढूंढता हूं।",
        "मैं खोल रही हूँ",
        "Main check karungi",
        "मैं देखूंगी",
        "Screen read karke status check karta hoon.",
        "I'll check that now.",
    ):
        assert promises(words), words
    for words in (
        "Main aapki madad kar sakti hoon.",
        "क्या मैं कुछ और कर सकती हूँ?",
        "मैं जानती हूँ कि यह कठिन है।",
        "Kya main dekhungi?",
        "Timer 01:23 par hai.",
    ):
        assert not promises(words), words


@pytest.mark.parametrize("cut", [1, 2, 3, 7])
async def test_the_gates_eat_nothing_of_a_plain_answer(cut: int):
    # 2 Nov 2026, once: "दो और दो, प।". The final text is the provider's, untouched by these.
    from ira.models.leaked import MarkupGate

    text = "दो और दो चार होते हैं। क्या आप मुझसे कुछ और पूछना चाहेंगे?"
    think, markup, promise = ThinkGate(), MarkupGate(), PromiseGate()
    out = ""
    for i in range(0, len(text), cut):
        out += promise.feed(markup.feed(think.feed(text[i : i + cut])))
    out += promise.feed(markup.feed(think.flush()) + markup.flush()) + promise.flush()
    assert out + promise.take() == text


@pytest.mark.parametrize(
    "reply", ["You're welcome! Let me know if you need anything.", "Done, I'll be here."]
)
async def test_a_thanks_is_only_talk_whatever_the_model_says(reply: str):
    runtime, owner, ids, _ = world([reply])
    events = await turn(runtime, owner, "thank you", ids["mac"])
    assert events[-1]["text"] == reply
    assert len(runtime.test_provider.calls) == 1


async def test_a_courtesy_is_no_promise():
    assert not promises("Let me know if you need anything else.")
    assert not promises("I'll be here if you need me.")
    assert promises("Let me check that.") and promises("I'll check that.")
    assert not claims_done("I haven't done anything yet.")


async def test_saying_it_cannot_is_an_answer():
    words = "I can't read that window, and I will not try."
    runtime, owner, ids, _ = world([words])
    events = await turn(runtime, owner, "read my passwords", ids["mac"])
    assert events[-1]["text"] == words


async def test_words_that_are_not_promises_stay_when_the_rest_are_taken_out():
    words = "Paris is the capital. Let me check more."
    runtime, owner, ids, _ = world([words, words])
    events = await turn(runtime, owner, "capital of France", ids["mac"])
    assert events[-1]["text"] == "Paris is the capital."


async def test_a_forced_round_with_nothing_to_say_is_not_said_again_as_a_stock_line():
    runtime, owner, ids, _ = world(["Paris hai. Main dekhti hoon.", call("finish_turn", {})])
    events = await turn(runtime, owner, "capital of France", ids["mac"])
    assert events[-1]["text"] == "Paris hai."


async def test_a_tool_on_several_devices_goes_only_to_the_one_named():
    # 2 Nov 2026: asked for the Mac's calendar, it was read on the Mac, the Pixel and the iPhone.
    runtime, owner, ids, ran = world([])
    shared = DeviceTool("calendar_read", "Read the calendar.", NOTHING, "screen", 0)
    mac = runtime.hub.connections[ids["mac"].id]
    mac.tools = {**mac.tools, "calendar_read": shared}
    pixel_id = ids["pixel"].id
    runtime.test_provider.script = [
        call("calendar_read", {"device": "Pixel 7"}),
        call("calendar_read", {}),
        "Yeh hai.",
    ]
    await turn(runtime, owner, "mac ke calendar mein kya hai", ids["pixel"])
    assert (pixel_id, "calendar_read") not in ran
    assert ran == [(ids["mac"].id, "calendar_read")]


async def test_a_tool_on_several_devices_unnamed_runs_where_they_are():
    runtime, owner, ids, ran = world([call("calendar_read", {}), "Yeh hai."])
    shared = DeviceTool("calendar_read", "Read the calendar.", NOTHING, "screen", 0)
    mac = runtime.hub.connections[ids["mac"].id]
    mac.tools = {**mac.tools, "calendar_read": shared}
    await turn(runtime, owner, "kal ke calendar mein kya hai", ids["pixel"])
    assert ran == [(ids["pixel"].id, "calendar_read")]


@pytest.mark.parametrize(
    "words",
    [
        "मैकबुक अभी ऑफ़लाइन है, इसलिए मैं उसे एक्सेस नहीं कर पा रहा हूँ।",
        "पिक्सल 7 अभी ऑफ़लाइन है। इसलिए मैं मिस्ड कॉल देख नहीं सकता।",
        "मैं आपके मैकबुक को चेक करता हूँ, लेकिन ऐसा लगता है कि वह अभी ऑफलाइन है।",
        "Mac abhi offline hai, main use nahi dekh pa raha hoon.",
        "मैं TaskPulse का timer देख नहीं पा रहा हूं क्योंकि permission बंद है।",
        "Main timer dekh nahi pa raha hoon.",
        "Your MacBook is offline, so I'm unable to look.",
        "I can't read that window, and I will not try.",
    ],
)
def test_saying_it_cannot_is_no_promise_sentence_by_sentence(words: str):
    assert not promises(words)


@pytest.mark.parametrize(
    "words",
    [
        "आपका iPhone अभी offline है, इसलिए मैं नहीं देख सकता। जब यह online आएगा तो मैं बता दूंगा।",
        "I can't see the battery from here. Let me check the apps.",
        "Your MacBook is offline right now, I'll tell you when it is back.",
    ],
)
def test_a_promise_beside_a_cannot_is_still_one(words: str):
    assert promises(words)


async def test_a_sentence_saying_it_cannot_goes_out_at_once():
    gate = PromiseGate()
    assert gate.feed("Mac abhi offline hai, main nahi dekh pa raha hoon. Aur") == (
        "Mac abhi offline hai, main nahi dekh pa raha hoon."
    )


async def test_the_device_off_takes_no_extra_round_and_loses_only_the_promise():
    words = "आपका MacBook अभी ऑफ़लाइन है, मैं नहीं देख सकता। जब यह online आएगा तो मैं बता दूंगा।"
    runtime, owner, ids, ran = world([words], offline=("mac",))
    events = await turn(runtime, owner, "मैकबुक पर टाइमर चेक करो", ids["pixel"])
    assert events[-1]["text"] == "आपका MacBook अभी ऑफ़लाइन है, मैं नहीं देख सकता।"
    assert len(runtime.test_provider.calls) == 1 and ran == []


async def test_the_device_off_with_only_a_promise_to_say_still_gets_its_round():
    answer = call("finish_turn", {"say": "MacBook is offline."})
    runtime, owner, ids, _ = world(["Main dekhti hoon.", answer], offline=("mac",))
    events = await turn(runtime, owner, "mac par timer dekho", ids["pixel"])
    assert events[-1]["text"] == "MacBook is offline."


async def test_i_cannot_then_let_me_check_goes_on_when_the_device_is_up():
    runtime, owner, ids, ran = world(
        ["I can't see the battery here. Let me check the apps.", call("screen_read"), "It is 80%."]
    )
    events = await turn(runtime, owner, "mac ki battery kitni hai", ids["pixel"])
    assert [name for _, name in ran] == ["screen_read"] and "80%" in events[-1]["text"]


@pytest.mark.parametrize(
    "said",
    ["Read my password app on the Mac", "mac par 1Password padho", "मैक पर पासवर्ड ऐप पढ़ो"],
)
async def test_a_password_app_refused_is_answered_not_forced(said: str):
    words = "I won't read your password app on the Mac."
    runtime, owner, ids, ran = world([words])
    events = await turn(runtime, owner, said, ids["pixel"])
    assert events[-1]["text"] == words and ran == []
    assert len(runtime.test_provider.calls) == 1


async def test_a_named_device_refused_otherwise_is_still_asked_to_go_on():
    words = "I can't reach your Mac from here."
    runtime, owner, ids, ran = world([words, call("screen_read"), "Timer 01:23."])
    events = await turn(runtime, owner, "mac par timer dekho", ids["pixel"])
    assert [name for _, name in ran] == ["screen_read"] and events[-1]["text"] == "Timer 01:23."


async def test_one_device_tool_is_tried_three_rounds_then_answered_with():
    runtime, owner, ids, ran = world(
        [call("screen_read"), call("screen_read"), call("screen_read"), "Yeh mila."]
    )
    events = await turn(runtime, owner, "screen padho", ids["mac"])
    assert [name for _, name in ran] == ["screen_read"] * 3
    assert "screen_read" not in offered(runtime, 3) and events[-1]["text"] == "Yeh mila."


async def test_a_tool_called_again_after_its_rounds_does_not_run():
    runtime, owner, ids, ran = world(
        [call("screen_read")] * 4 + ["Yeh mila."],
    )
    events = await turn(runtime, owner, "screen padho", ids["mac"])
    assert [name for _, name in ran] == ["screen_read"] * 3
    result = next(
        e for e in events if e["type"] == "tool_result" and "already been tried" in e["result"]
    )
    assert result["ok"] is False and events[-1]["text"] == "Yeh mila."


async def test_a_screen_job_goes_on_step_by_step_past_three_rounds():
    # Read, act, read again: a screen tool between other steps is no flailing.
    steps = [call("screen_read"), call("app_open", {"name": "Safari"})] * 3
    runtime, owner, ids, ran = world([*steps, call("screen_read"), "Yeh mila."])
    events = await turn(runtime, owner, "screen padho aur Safari kholo", ids["mac"])
    assert [name for _, name in ran] == ["screen_read", "app_open"] * 3 + ["screen_read"]
    results = [e["result"] for e in events if e["type"] == "tool_result"]
    assert not any("already been tried" in result for result in results)


async def test_reading_one_window_after_another_is_no_flailing():
    windows = [call("screen_read", {"app": app}) for app in ("Safari", "Mail", "Notes", "Slack")]
    runtime, owner, ids, ran = world([*windows, "Yeh mila."])
    await turn(runtime, owner, "sab windows padho", ids["mac"])
    assert [name for _, name in ran] == ["screen_read"] * 4


async def test_another_device_tool_still_has_three_rounds_whatever_it_is_asked():
    days = [call("calendar_read", {"day": day}) for day in (1, 2, 3, 4)]
    runtime, owner, ids, ran = world([*days, "Kuch nahi mila."])
    await turn(runtime, owner, "calendar dekho", ids["pixel"])
    assert [name for _, name in ran] == ["calendar_read"] * 3


async def test_several_calls_in_one_round_count_as_one():
    three = ChatResponse(
        text="", tool_calls=[ToolCall(f"c{n}", "screen_read", "{}") for n in range(5)]
    )
    runtime, owner, ids, ran = world([three, "Yeh mila."])
    await turn(runtime, owner, "screen padho", ids["mac"])
    assert len(ran) == 5


async def test_out_of_steps_its_promises_are_cut_and_what_it_found_stands():
    runtime, owner, ids, _ = world(
        [call("screen_read"), call("screen_read"), "Timer 01:23 hai. Main aur dekhti hoon."]
    )
    runtime.assistant.max_tool_rounds = 2
    events = await turn(runtime, owner, "screen padho", ids["mac"])
    assert events[-1]["text"] == "Timer 01:23 hai."
    assert said(events) == "Timer 01:23 hai."


async def test_out_of_steps_with_only_a_promise_says_what_was_tried():
    runtime, owner, ids, _ = world([call("screen_read"), "Main aur dekhti hoon."])
    runtime.assistant.max_tool_rounds = 1
    events = await turn(runtime, owner, "screen padho", ids["mac"])
    assert "I tried screen_read" in events[-1]["text"]
