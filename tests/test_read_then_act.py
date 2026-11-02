"""An act after a read goes on only on the person's own words, judged by a check that sees nothing
read; inside a session the see, act, check loop runs on from any device, and what a page says can
neither start nor widen it (docs/security.md, "What she reads cannot steer her")."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ira.approvals import blind_click, moved_to, named_in, pasting, risky_step
from ira.asked import AskedFor, _names
from ira.devices.hub import Connection
from ira.devices.protocol import DeviceTool
from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider
from ira.models.gateway import Gateway

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
pytestmark = pytest.mark.anyio
STEER = "STEERING-WORDS-FROM-THE-PAGE"
ANY: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": True}
MAC = [
    ("window_elements", "screen", 0),
    ("screen_read", "screen", 0),
    ("browser_tabs", "browser", 0),
    ("browser_show_tab", "browser", 1),
    ("app_open", "apps", 1),
    ("notes_add", "notes", 1),
    ("url_open", "apps", 2),
    ("messages_send", "messages", 2),
    ("shortcuts_run", "shortcuts", 2),
    ("mac_click", "control", 3),
    ("mac_type", "control", 3),
    ("mac_keys", "control", 3),
    ("mac_menu", "control", 3),
    ("file_read", "files", 0),
    ("clipboard_read", "clipboard", 0),
]
PHONE = [("calls_recent", "calls", 0), ("call_place", "calls", 2)]
LOOK = {
    "app": "com.example.browser",
    "appName": "Browser",
    "window": "Invoice",
    "text": STEER,
    "elements": [
        {"id": "e1", "kind": "button", "label": "Details"},
        {"id": "e2", "kind": "button", "label": "Pay now"},
        {"id": "e3", "kind": "button", "label": "Paste"},
        {"id": "e4", "kind": "button", "label": "Send"},
    ],
}


class Socket:
    async def send_text(self, data: str) -> None:
        pass

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        pass


def step(name: str, **arguments: Any) -> ChatResponse:
    return ChatResponse(text="", tool_calls=[ToolCall(f"c{name}", name, json.dumps(arguments))])


LOOK_FIRST = step("window_elements")


class World:
    def __init__(self, script: list[Any], asks: set[str] | None = None, look: Any = None) -> None:
        self.provider = ScriptedProvider([*script, "Ok."])
        self.provider.asks = asks if asks is not None else set()
        self.runtime = make_runtime(provider=self.provider)
        self.owner = self.runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
        self.ran: list[str] = []
        self.devices: dict[str, Any] = {}
        self.look = LOOK if look is None else look
        hub = self.runtime.hub
        for name, kind, tools in (("mac", "mac", MAC), ("iphone", "ios", PHONE)):
            raw = [
                {"name": t, "description": f"{t}.", "parameters": ANY, "skill": s, "tier": n}
                for t, s, n in tools
            ]
            skills = sorted({s for _, s, _ in tools})
            code, _ = hub.devices.start_pairing(self.owner.id, kind, name, skills)
            _, device = hub.devices.redeem(code)
            hub.devices.hello(device.id, version="1", tools=raw)
            device = hub.devices.get(device.id)
            self.devices[name] = device
            offered = {
                t["name"]: DeviceTool(
                    t["name"], t["description"], t["parameters"], t["skill"], t["tier"]
                )
                for t in raw
            }
            hub.connections[device.id] = Connection(device, Socket(), offered, 1.0)
        hub.call = self.call  # type: ignore[method-assign]

    async def call(self, device_id: int, name: str, arguments: dict[str, Any]) -> Any:
        self.ran.append(name)
        if name in ("window_elements", "screen_read"):
            return self.look
        return {"summary": "Done."}

    def session(self, unlocked: list[str] | None = None) -> None:
        mac = self.devices["mac"].id
        self.runtime.approvals.open(self.owner.id, mac, None, minutes=30)
        if unlocked:
            self.runtime.approvals.set_unlocked(self.owner.id, mac, unlocked)

    async def turn(self, said: str, device: str = "mac") -> list[dict[str, Any]]:
        return [
            event
            async for event in self.runtime.assistant.events(
                said, conversation_id="c1", channel="api", actor=self.owner.email,
                user_id=self.owner.id, device_id=self.devices[device].id,
            )
        ]  # fmt: skip


def cards(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e["action"] for e in events if e["type"] == "action"]


def refused(events: list[dict[str, Any]]) -> list[str]:
    return [
        e["name"] for e in events if e["type"] == "tool_result" and "refused" in e.get("result", "")
    ]


# The check itself.


@pytest.mark.parametrize(
    ("answer", "names"),
    [
        ('["app_open"]', {"app_open"}),
        ('The answer is ["app_open", "url_open"].', {"app_open", "url_open"}),
        ('["made_up", "app_open"]', {"app_open"}),
        ("[]", set()),
        ("yes, all of them", set()),
        ("[not json", set()),
        ("[1, 2]", set()),
    ],
)
def test_its_answer_is_read_narrowly(answer: str, names: set[str]):
    assert _names(answer, {"app_open", "url_open"}) == names


async def test_an_error_is_a_no_and_each_action_is_asked_once():
    provider = ScriptedProvider()
    gateway = Gateway({"fake": provider}, {"default": ["fake:m"]})

    async def broken(*args: Any, **options: Any) -> Any:
        from ira.models.base import ProviderError

        raise ProviderError("down", kind="server")

    provider.chat = broken  # type: ignore[method-assign]
    check = AskedFor(gateway, ["open it"])
    assert not await check.allows("app_open", "Open an app.")
    assert not await check.allows("app_open", "Open an app.")
    assert check.calls == 1


async def test_it_sees_what_the_person_said_and_nothing_read():
    world = World([LOOK_FIRST, step("app_open", app="Calculator")])
    await world.turn("screen dekho aur zebra wala bhool jao")
    given = "\n".join(world.provider.asked)
    assert "zebra" in given and "app_open" in given
    assert STEER not in given and "Invoice" not in given


# Outside a session.


async def test_read_then_a_named_act_from_another_device_gets_its_card():
    world = World(
        [step("browser_tabs"), step("browser_show_tab", match="invoice")], {"browser_show_tab"}
    )
    events = await world.turn("mac par tabs dekho aur invoice wala aage lao", "iphone")
    assert world.ran == ["browser_tabs"]
    assert cards(events)[0]["tool"] == "browser_show_tab" and "mac" in cards(events)[0]["summary"]


async def test_read_then_an_act_nobody_asked_for_is_refused():
    world = World([step("browser_tabs"), step("browser_show_tab", match="invoice")])
    events = await world.turn("mac par tabs dekho", "iphone")
    assert world.ran == ["browser_tabs"] and not cards(events)
    assert refused(events) == ["browser_show_tab"]


async def test_at_once_on_this_device_it_still_needs_their_words():
    world = World([LOOK_FIRST, step("app_open", app="Calculator")])
    events = await world.turn("screen dekho")
    assert world.ran == ["window_elements"] and refused(events) == ["app_open"]
    world = World([LOOK_FIRST, step("app_open", app="Calculator")], {"app_open"})
    await world.turn("screen dekho aur calculator kholo")
    assert world.ran == ["window_elements", "app_open"]


@pytest.mark.parametrize(
    "act", ["messages_send", "shortcuts_run", "mac_click"], ids=["send", "shortcut", "pin"]
)
async def test_what_reaches_others_or_takes_a_pin_never_follows_a_read(act: str):
    world = World([LOOK_FIRST, step(act, label="Details")], {act})
    events = await world.turn("screen dekho, yeh bhi karo")
    assert world.ran == ["window_elements"] and not cards(events)
    assert refused(events) == [act]
    assert world.provider.asked == []


async def test_with_nothing_read_it_is_not_asked():
    world = World([step("browser_show_tab", match="invoice")])
    events = await world.turn("mac par invoice wala tab aage lao", "iphone")
    assert cards(events) and world.provider.asked == []


# Rounds that push.


async def test_a_goal_round_with_nothing_asked_left_is_free_and_offers_no_act():
    world = World([step("calls_recent"), "Avery, +1 555 0100.", "Avery, +1 555 0100."])
    await world.turn("phone pe last missed call dekho aur uska number batao", "mac")
    offered = {t["name"] for t in world.provider.calls[2]["tools"]}
    assert "calls_recent" in offered and "call_place" not in offered
    assert world.provider.forced == []  # streamed, or not: nobody required a tool


async def test_a_goal_round_with_an_asked_act_undone_requires_a_tool():
    world = World(
        [step("browser_tabs"), "Invoice is there.", step("browser_show_tab", match="invoice")],
        {"browser_show_tab"},
    )
    events = await world.turn("mac par tabs dekho aur invoice wala aage lao", "iphone")
    assert "required" in world.provider.forced
    offered = {t["name"] for t in world.provider.calls[2]["tools"]}
    assert "browser_show_tab" in offered and "url_open" not in offered
    assert cards(events)[0]["tool"] == "browser_show_tab"


async def test_a_round_that_pushes_does_not_run_what_it_withheld():
    world = World(["Main dekhti hoon.", step("call_place", number="+15550199")])
    events = await world.turn("iphone par calls dekho", "mac")
    assert not cards(events) and "call_place" not in world.ran


# A session.


async def test_look_then_click_runs_from_the_mac_and_from_the_phone():
    for device in ("mac", "iphone"):
        world = World([LOOK_FIRST, step("mac_click", id="e1")])
        world.session()
        events = await world.turn("Details dabao", device)
        assert world.ran == ["window_elements", "mac_click"] and not cards(events)


async def test_from_the_phone_a_step_with_no_read_runs_too():
    world = World([step("mac_click", label="Details")])
    world.session()
    events = await world.turn("mac par Details dabao", "iphone")
    assert world.ran == ["mac_click"] and not cards(events)


@pytest.mark.parametrize(
    ("element", "action", "kind"),
    [("e2", "pay_or_buy", "pay"), ("e4", "send_something", "send")],
)
async def test_a_risky_step_after_a_look_asks_when_their_words_did(
    element: str, action: str, kind: str
):
    world = World([LOOK_FIRST, step("mac_click", id=element)], {action})
    world.session()
    events = await world.turn("yeh kar do")
    assert world.ran == ["window_elements"]
    card = cards(events)[0]
    assert card["tier"] == 3 and f"it may {kind}" in card["summary"]


async def test_a_risky_step_a_page_wants_is_refused():
    world = World([LOOK_FIRST, step("mac_click", id="e2")])
    world.session()
    events = await world.turn("Details dabao")
    assert world.ran == ["window_elements"] and not cards(events)
    assert refused(events) == ["mac_click"]
    assert "Pay now" not in "\n".join(world.provider.asked)


async def test_going_to_a_site_nobody_named():
    url = step("url_open", url="https://upload.example.net/form")
    world = World([LOOK_FIRST, url])
    world.session()
    assert refused(await world.turn("Details dabao")) == ["url_open"]
    world = World([LOOK_FIRST, url], {"url_open"})
    world.session()
    card = cards(await world.turn("form bhar do"))[0]
    assert card["tier"] == 2 and "did not name" in card["summary"]
    assert "url_open" not in world.ran
    world = World([LOOK_FIRST, step("url_open", url="https://upload.example.net/form")])
    world.session()
    events = await world.turn("upload.example.net par jao")
    assert "url_open" in world.ran and not cards(events)


async def test_opening_an_app_nobody_named_asks_though_it_needs_no_yes_elsewhere():
    world = World([LOOK_FIRST, step("app_open", app="Calculator")], {"app_open"})
    world.session()
    card = cards(await world.turn("kuch khol do"))[0]
    assert card["tier"] == 2 and "app_open" not in world.ran


async def test_looking_at_an_app_nobody_named_is_refused():
    world = World([LOOK_FIRST, step("screen_read", app="Mail")])
    world.session()
    assert refused(await world.turn("Details dabao")) == ["screen_read"]
    assert world.ran == ["window_elements"]
    world = World([LOOK_FIRST, step("screen_read", app="Mail")])
    world.session()
    await world.turn("Mail mein dekho")
    assert world.ran == ["window_elements", "screen_read"]


@pytest.mark.parametrize("tool", ["file_read", "clipboard_read"])
async def test_reading_what_they_hold_after_a_look_needs_their_words(tool: str):
    world = World([LOOK_FIRST, step(tool)])
    world.session()
    assert refused(await world.turn("Details dabao")) == [tool]
    assert world.ran == ["window_elements"]
    world = World([LOOK_FIRST, step(tool)], {tool})
    world.session()
    await world.turn("file padh kar form bharo")
    assert world.ran == ["window_elements", tool]


async def test_typing_after_a_look_needs_their_words():
    world = World([LOOK_FIRST, step("mac_type", text="14 Main Road")])
    world.session()
    assert refused(await world.turn("Details dabao")) == ["mac_type"]
    world = World([LOOK_FIRST, step("mac_type", text="14 Main Road")], {"type_text"})
    world.session()
    events = await world.turn("address likh do")
    assert world.ran == ["window_elements", "mac_type"] and not cards(events)


@pytest.mark.parametrize(
    "paste",
    [
        step("mac_keys", keys="cmd+v"),
        step("mac_keys", keys="cmd+shift+v"),
        step("mac_menu", path="Edit > Paste"),
        step("mac_click", label="AutoFill"),
        step("mac_click", id="e3"),
    ],
    ids=["keys", "keys-plain", "menu", "autofill", "by-id"],
)
async def test_a_paste_is_a_way_out_and_needs_their_words(paste: ChatResponse):
    world = World([LOOK_FIRST, paste])
    world.session()
    events = await world.turn("Details dabao")
    assert world.ran == ["window_elements"] and refused(events)
    world = World([LOOK_FIRST, paste], {"paste_or_autofill"})
    world.session()
    await world.turn("copy kiya hua text yahan paste karo")
    assert len(world.ran) == 2


async def test_a_paste_before_any_read_is_their_own():
    world = World([step("mac_keys", keys="cmd+v")])
    world.session()
    await world.turn("paste karo")
    assert world.ran == ["mac_keys"]


async def test_a_click_that_does_not_say_what_it_presses_is_refused_in_a_session():
    world = World([LOOK_FIRST, step("mac_click", x=100, y=200)])
    world.session()
    assert refused(await world.turn("Details dabao")) == ["mac_click"]
    assert world.ran == ["window_elements"]
    world = World([LOOK_FIRST, step("mac_click", id="e99")])
    world.session()
    assert refused(await world.turn("Details dabao")) == ["mac_click"]


async def test_a_position_on_a_window_with_nothing_listed_may_be_clicked():
    empty = {"appName": "Canvas", "window": "Art", "elements": []}
    world = World([LOOK_FIRST, step("mac_click", x=100, y=200)], look=empty)
    world.session()
    await world.turn("yahan dabao")
    assert world.ran == ["window_elements", "mac_click"]


async def test_turning_it_on_never_follows_a_read():
    world = World([step("screen_read"), step("control_start", minutes=60)], {"control_start"})
    events = await world.turn("screen padho")
    assert not cards(events) and not world.runtime.approvals.for_user(world.owner.id)


TERMINAL = {"app": "com.apple.Terminal", "appName": "Terminal", "window": "bash", "elements": []}


async def test_unlocked_a_return_after_a_read_shows_what_will_run():
    world = World(
        [LOOK_FIRST, step("mac_type", text="ls -la", pressReturn=True)],
        {"type_text", "run_command"},
        look=TERMINAL,
    )
    world.session(["terminals"])
    card = cards(await world.turn("Terminal mein ls chalao"))[0]
    assert card["tier"] == 2 and "It will run: ls -la" in card["summary"]
    assert world.ran == ["window_elements"]


async def test_unlocked_plain_typing_flows_and_its_return_names_the_text():
    world = World(
        [LOOK_FIRST, step("mac_type", text="ls -la"), step("mac_keys", keys="return")],
        {"type_text", "run_command"},
        look=TERMINAL,
    )
    world.session(["terminals"])
    card = cards(await world.turn("Terminal mein ls chalao"))[0]
    assert world.ran == ["window_elements", "mac_type"]
    assert card["tier"] == 2 and "It will run: ls -la" in card["summary"]


async def test_unlocked_a_command_a_page_wants_is_refused():
    world = World([LOOK_FIRST, step("mac_keys", keys="return")], look=TERMINAL)
    world.session(["terminals"])
    assert refused(await world.turn("Terminal mein kya likha hai")) == ["mac_keys"]


async def test_locked_it_stays_refused_with_no_card():
    world = World([LOOK_FIRST, step("mac_keys", keys="return")], {"run_command"}, look=TERMINAL)
    world.session()
    events = await world.turn("Terminal mein ls chalao")
    assert refused(events) == ["mac_keys"] and not cards(events)
    assert not world.runtime.approvals.for_user(world.owner.id)  # a step reached Terminal


async def test_the_check_is_given_the_words_that_started_it_and_their_last_few():
    world = World(
        ["Ok.", LOOK_FIRST, step("mac_type", text="x"), "Ok."],
        {"type_text"},
    )
    world.session()
    world.runtime.assistant._session_words[world.owner.id] = ["form mein naam likh do"]
    await world.turn("kuch nahi")
    await world.turn("haan wahi karo")
    given = world.provider.asked[-1]
    assert "form mein naam likh do" in given and "haan wahi karo" in given and STEER not in given


async def test_control_start_keeps_the_words_and_they_go_with_the_session():
    world = World([step("control_start", minutes=30)])
    await world.turn("mera mac control karo aur form bharo")
    assistant = world.runtime.assistant
    assert assistant._session_words[world.owner.id] == ["mera mac control karo aur form bharo"]
    world.provider.script = ["Ok."]
    await world.turn("kuch aur")  # no window was opened: nothing is kept for it
    assert world.owner.id not in assistant._session_words


# The pure parts.


@pytest.mark.parametrize(
    ("words", "place", "named"),
    [
        ("youtube kholo", "https://www.youtube.com/watch", True),
        ("mail.google.com kholo", "https://mail.google.com/", True),
        ("form bhar do", "https://upload.example.net/form", False),
        ("taskpulse dekho", "com.example.TaskPulse", True),
        ("youtube kholo", "https://youtube.evil.example/", False),
        ("sunrise kholo", "https://www.sunrise.co.uk/news", True),
        ("x kholo mixed", "https://x.com/", True),
        ("next dabao", "https://x.com/", False),
        ("Details dabao", "Calculator", False),
        ("मैक पर सफारी खोलो", "Safari", False),  # another script: it only asks
    ],
)
def test_a_place_named_in_their_words(words: str, place: str, named: bool):
    assert named_in(words, place) is named


def test_what_a_step_goes_to():
    assert moved_to("url_open", {"url": "https://a.example"}) == "https://a.example"
    assert moved_to("mac_click", {"app": "Mail", "id": "e1"}) == "Mail"
    assert moved_to("mac_click", {"id": "e1"}) is None


@pytest.mark.parametrize(
    "arguments",
    [
        {"keys": "cmd+v"},
        {"keys": "ctrl+v"},
        {"keys": "command+shift+v"},
        {"path": "Edit > Paste and Match Style"},
        {"label": "Autofill password"},
    ],
)
def test_what_counts_as_pasting(arguments: dict[str, Any]):
    assert pasting("mac_keys", arguments, None)


def test_what_does_not_count_as_pasting():
    assert not pasting("mac_keys", {"keys": "cmd+vv"}, None)
    assert not pasting("mac_click", {"label": "Details"}, None)


def test_sending_is_a_risky_step_now():
    assert risky_step("mac_click", {"label": "Send"}, None)
    assert risky_step("mac_click", {"label": "भेजें"}, None)
    looked = {"appName": "Slack", "window": "general"}
    assert risky_step("mac_type", {"text": "hi", "pressReturn": True}, looked)
    assert not risky_step("mac_type", {"text": "hi"}, looked)
    assert not risky_step("mac_click", {"label": "Sender"}, None)


def test_a_click_that_says_nothing():
    looked = {"elements": {"e1": "Details"}}
    assert blind_click("mac_click", {"x": 1, "y": 2}, looked)
    assert blind_click("mac_click", {"id": "e2"}, looked)
    assert not blind_click("mac_click", {"id": "e1"}, looked)
    assert not blind_click("mac_click", {"label": "Details"}, looked)
    assert not blind_click("mac_click", {"x": 1, "y": 2}, {"elements": {}})
    assert not blind_click("mac_type", {"x": 1}, looked)
