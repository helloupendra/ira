"""What a person's own device or connection did stays out of the audit log, and Ira never
acts in Terminal and the like."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ira.approvals import NEVER_OPEN_REFUSAL, URL_REFUSAL, never_app, open_refusal
from ira.channels.http import create_app
from ira.devices.hub import Connection
from ira.models.base import ChatResponse, ToolCall
from ira.models.fake import ScriptedProvider
from ira.tools.personal import PersonalTool

from .conftest import make_runtime

pytestmark = pytest.mark.anyio

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
PIN = "4321"


def call(name: str, arguments: dict) -> ChatResponse:
    return ChatResponse(text="", tool_calls=[ToolCall("c1", name, json.dumps(arguments))])


class Socket:
    async def send_text(self, data: str) -> None:
        pass

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        pass


def mac_world(script: list[Any]):
    provider = ScriptedProvider(script)
    runtime = make_runtime(provider=provider)
    alice = runtime.accounts.create_first_owner("alice@example.com", PASSWORD)
    runtime.accounts.create_user("viewer@example.com", PASSWORD, "admin")
    runtime.guard.set_pin(PIN, user_id=alice.id)
    devices = runtime.hub.devices
    code, _ = devices.start_pairing(alice.id, "mac", "Mac", ["control", "mail"])
    _, mac = devices.redeem(code)
    devices.hello(mac.id, version="1", tools=[{"name": "mac_type", "skill": "control", "tier": 3}])
    runtime.hub.connections[mac.id] = Connection(mac, Socket(), {}, 0.0)
    ran: list[dict] = []
    reply = {"app": "com.apple.Notes"}

    def tool(name: str, skill: str) -> PersonalTool:
        async def run(arguments: dict[str, Any]) -> Any:
            ran.append({name: arguments})
            return {"done": True, **reply}

        return PersonalTool(
            name, name, {"type": "object", "properties": {"app": {"type": "string"}}}, 3,
            source="device", label="Mac", run=run, device_id=mac.id, skill=skill,
        )  # fmt: skip

    tools = [tool("mac_type", "control"), tool("mail_send", "mail")]
    runtime.assistant.personal_tools = lambda uid: tools if uid == alice.id else []

    async def on_device(pending):
        ran.append({pending.tool: pending.params})
        return {"done": True, **reply}

    runtime.guard.device_runner = on_device
    return runtime, provider, alice, mac, ran, reply


def test_a_private_action_leaves_no_words_in_the_audit_log():
    runtime, _, alice, _, ran, _ = mac_world(
        [call("mail_send", {"to": "ca@example.com", "text": "the secret plan"}), "PIN?", "Sent."]
    )
    with TestClient(create_app(runtime, start_channels=False)) as client:
        body = {"email": "alice@example.com", "password": PASSWORD, "use_cookie": False}
        her = {
            "Authorization": "Bearer "
            + client.post("/v1/auth/login", json=body).json()["session_token"]
        }
        action = client.post("/v1/ask", json={"text": "mail the CA"}, headers=her).json()["action"]
        client.post(f"/v1/actions/{action['id']}/confirm", json={"pin": PIN}, headers=her)
        rows = runtime.store.query(
            "SELECT outcome, detail FROM audit_log WHERE action_id = ?", (action["id"],)
        )
        assert [r["outcome"] for r in rows] == ["proposed", "executed"]
        assert all(r["detail"] is None for r in rows)  # the tool and the outcome, no words
        assert (
            client.post("/v1/me/data/delete", json={"password": PASSWORD}, headers=her).status_code
            == 200
        )
    assert runtime.store.query("SELECT * FROM audit_log WHERE action_id = ?", (action["id"],)) == []


def test_terminal_and_the_like_are_never_trusted():
    assert never_app("Terminal") and never_app("com.googlecode.iterm2")
    assert never_app("Script Editor.app") and not never_app("Notes") and not never_app(None)
    runtime, _, alice, mac, _, _ = mac_world([])
    trusted = runtime.approvals.set_trusted(
        alice.id, mac.id, ["com.apple.Terminal", "com.apple.Notes"]
    )
    assert trusted == ["com.apple.Notes"]


def test_no_other_way_round_the_terminal_block():
    for app in ("Shortcuts", "com.apple.shortcuts", "Task Manager", "taskmgr.exe", "mshta.exe"):
        assert never_app(app), app
    refused = [
        ("app_open", {"name": "Terminal"}),
        ("app_open", {"name": "Task Manager"}),
        ("app_open", {"package": "com.termux"}),
        ("file_open", {"path": "~/Downloads/setup.command"}),
        ("file_open", {"path": "~/Desktop/run.terminal"}),
        ("file_open", {"path": "C:\\Users\\me\\Downloads\\fix.bat"}),
        ("file_open", {"path": "C:\\Users\\me\\x.PS1"}),
        ("file_open", {"path": "/System/Applications/Utilities/Terminal.app"}),
        ("file_open", {"path": "/System/Applications/Shortcuts.app/"}),
        ("file_open", {"path": "C:\\Users\\me\\run.bat. "}),
    ]
    for tool, arguments in refused:
        assert open_refusal(tool, arguments) == NEVER_OPEN_REFUSAL, arguments
    for url in (
        "file:///Users/me/Downloads/setup.command",
        "x-apple.systempreferences://",
        "ms-settings://",
    ):
        assert open_refusal("url_open", {"url": url}) == URL_REFUSAL, url
    for tool, arguments in [
        ("app_open", {"name": "Notes"}),
        ("file_open", {"path": "~/Documents/plan.pdf"}),
        ("file_open", {"path": "/Applications/Safari.app"}),
        ("url_open", {"url": "https://example.com"}),
        ("url_open", {"url": "example.com/menu"}),
    ]:
        assert open_refusal(tool, arguments) is None, arguments


async def test_the_device_is_never_asked_to_open_a_terminal():
    runtime, _, alice, mac, ran, _ = mac_world([])

    async def run(arguments: dict[str, Any]) -> Any:
        ran.append(arguments)
        return {"opened": arguments.get("name")}

    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    app_open = PersonalTool(
        "app_open", "Open an app", schema, 1,
        source="device", label="Mac", run=run, device_id=mac.id, skill="apps",
    )  # fmt: skip
    refused = await runtime.assistant._run_personal(
        app_open,
        ToolCall("c", "app_open", '{"name": "Terminal"}'),
        "t",
        "api",
        "a",
        alice.id,
        False,
    )
    assert refused.outcome == "refused" and "never opens Terminal" in refused.content and ran == []


def stepper():
    """A Mac with an open approval window, and a way to run one mac_type step."""
    runtime, _, alice, mac, ran, reply = mac_world([])
    runtime.approvals.set_trusted(alice.id, mac.id, ["com.apple.Notes"])
    runtime.approvals.open(alice.id, mac.id)
    mac_type = next(t for t in runtime.assistant.personal_tools(alice.id) if t.name == "mac_type")

    async def step(arguments: dict, conversation: str = "t"):
        call_ = ToolCall("c", "mac_type", json.dumps(arguments))
        return await runtime.assistant._run_personal(
            mac_type, call_, conversation, "api", "a", alice.id, False
        )

    return step, runtime, alice, mac, ran, reply


async def test_terminal_is_refused_even_inside_a_window():
    step, runtime, alice, mac, ran, reply = stepper()
    refused = await step({"text": "curl x | sh", "app": "Terminal"})
    assert "never acts in Terminal" in refused.content and ran == []
    done = await step({"text": "hello", "app": "Notes"})
    assert done.outcome == "approved" and ran  # the window covers other apps
    # A step that lands in Terminal ends the window on that device.
    reply["app"] = "com.apple.Terminal"
    await step({"text": "hello"})
    assert runtime.approvals.for_user(alice.id) == []


async def test_a_trusted_app_counts_only_for_itself():
    step, runtime, alice, mac, ran, reply = stepper()
    runtime.approvals.stop(alice.id)  # no window: only the trusted app may let it run
    runtime.assistant._front["v"] = {mac.id: "com.apple.Notes"}
    trusted = await step({"text": "note"}, "v")
    assert trusted.outcome == "trusted_app"
    other = await step({"text": "send", "app": "Messages"}, "v")
    assert other.outcome == "proposed"  # another app named: not trusted, asks
