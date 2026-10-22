"""The daemon against a fake IRA server on 127.0.0.1: hello, calls, pings, silence, reconnects."""

from __future__ import annotations

import asyncio
import json

import pytest
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from ira_mac.daemon import Daemon, close_code, websocket_connect
from ira_mac.tools import Toolbox

from .conftest import FakeBrowser

TOKEN = "irad_" + "t" * 43

TABS = [
    {
        "id": 7,
        "title": "Upload - Example Drive",
        "url": "https://drive.example.com/up",
        "active": True,
        "focused": True,
    }
]
PAGE = {
    "title": "Upload - Example Drive",
    "url": "https://drive.example.com/up",
    "text": "quarterly-report.pdf 63% uploaded",
    "progress": {"bars": [{"percent": 63}], "eta": ["4 min"]},
}


class FakeServer:
    """Plays the IRA server: records what the device sends and runs a script per connection."""

    def __init__(self, script):
        self.script = script  # async callable(ws, server)
        self.connections = 0
        self.headers = []
        self.hellos = []

    async def handler(self, ws):
        self.connections += 1
        self.headers.append(ws.request.headers.get("Authorization"))
        hello = json.loads(await ws.recv())
        self.hellos.append(hello)
        await ws.send(json.dumps({"type": "welcome", "deviceId": 3, "skills": ["chrome"]}))
        await self.script(ws, self)


async def recv_type(ws, kind, timeout=3.0):
    while True:
        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if frame.get("type") == kind:
            return frame


def make_daemon(url, browser=None, **kwargs):
    browser = browser or FakeBrowser(TABS, {7: PAGE})
    holder = []
    tools = Toolbox(browser, lambda *event: holder[0](*event), poll_seconds=0.05)
    daemon = Daemon(url, lambda: TOKEN, tools, label="Test Mac", backoff=(0.05,), **kwargs)
    holder.append(daemon.announce)
    return daemon


async def run_with(script, check, **daemon_kwargs):
    server = FakeServer(script)
    async with serve(server.handler, "127.0.0.1", 0) as ws_server:
        port = ws_server.sockets[0].getsockname()[1]
        daemon = make_daemon(f"ws://127.0.0.1:{port}/v1/devices/ws", **daemon_kwargs)
        task = asyncio.create_task(daemon.run_forever())
        try:
            await asyncio.wait_for(check(server, daemon), 10)
        finally:
            daemon.stop()
            await asyncio.wait_for(task, 5)
            await daemon.tools.stop()
    return server


def test_hello_call_and_result():
    answers = []

    async def script(ws, server):
        await ws.send(
            json.dumps(
                {"type": "call", "id": "c1", "tool": "chrome_read_tab", "args": {"match": "upload"}}
            )
        )
        answers.append(await recv_type(ws, "result"))
        await ws.send(
            json.dumps({"type": "call", "id": "c2", "tool": "chrome_close_tab", "args": {}})
        )
        answers.append(await recv_type(ws, "result"))
        await ws.wait_closed()

    async def check(server, daemon):
        while len(answers) < 2:
            await asyncio.sleep(0.02)

    server = asyncio.run(run_with(script, check))
    assert server.headers == [f"Bearer {TOKEN}"]
    hello = server.hellos[0]
    assert (hello["type"], hello["kind"], hello["label"]) == ("hello", "mac", "Test Mac")
    assert [t["name"] for t in hello["tools"]] == [
        "chrome_list_tabs",
        "chrome_read_tab",
        "chrome_watch_tab",
    ]
    assert {t["skill"] for t in hello["tools"]} == {"chrome"}
    assert [t["tier"] for t in hello["tools"]] == [0, 0, 1]
    first, second = answers
    assert first["id"] == "c1" and first["ok"] is True
    assert first["content"]["summary"] == "Upload - Example Drive: 63%, about 4 min left"
    assert second == {
        "type": "result",
        "id": "c2",
        "ok": False,
        "error": "this Mac has no tool 'chrome_close_tab'",
    }


def test_chrome_not_answering_is_a_failed_result():
    class SlowBrowser(FakeBrowser):
        async def request(self, op, **fields):
            raise RuntimeError("Chrome did not answer within 15 seconds")

    answers = []

    async def script(ws, server):
        await ws.send(
            json.dumps({"type": "call", "id": "c1", "tool": "chrome_list_tabs", "args": {}})
        )
        answers.append(await recv_type(ws, "result"))
        await ws.wait_closed()

    async def check(server, daemon):
        while not answers:
            await asyncio.sleep(0.02)

    asyncio.run(run_with(script, check, browser=SlowBrowser()))
    assert answers[0]["ok"] is False and "did not answer" in answers[0]["error"]


def test_it_reconnects_after_the_server_drops_it():
    async def script(ws, server):
        if server.connections < 3:
            await ws.close()
        else:
            await ws.wait_closed()

    async def check(server, daemon):
        while server.connections < 3:
            await asyncio.sleep(0.02)

    server = asyncio.run(run_with(script, check))
    assert server.connections >= 3 and all(h["type"] == "hello" for h in server.hellos)


def test_ping_pong_and_silence():
    seen = []

    async def script(ws, server):
        if server.connections == 1:
            await ws.send(json.dumps({"type": "ping"}))
            seen.append(await recv_type(ws, "pong"))
            seen.append(await recv_type(ws, "ping"))  # the device pings on its own
        await ws.wait_closed()  # then the server goes quiet

    async def check(server, daemon):
        while server.connections < 2:  # silence made it reconnect
            await asyncio.sleep(0.02)

    asyncio.run(run_with(script, check, ping_seconds=0.1, silence_seconds=0.4))
    assert [frame["type"] for frame in seen] == ["pong", "ping"]


def test_answers_over_one_megabyte_are_replaced_by_an_error():
    big = dict(PAGE, text="x" * 1_100_000)
    answers = []

    async def script(ws, server):
        await ws.send(
            json.dumps({"type": "call", "id": "c1", "tool": "chrome_list_tabs", "args": {}})
        )
        answers.append(await recv_type(ws, "result"))
        await ws.wait_closed()

    async def check(server, daemon):
        while not answers:
            await asyncio.sleep(0.02)

    browser = FakeBrowser([dict(TABS[0], title="x" * 1_100_000)], {7: big})
    asyncio.run(run_with(script, check, browser=browser))
    assert answers[0] == {
        "type": "result",
        "id": "c1",
        "ok": False,
        "error": "the answer was larger than 1 MB",
    }


def test_a_watch_announces_once_and_events_are_spaced():
    events = []

    async def script(ws, server):
        await ws.send(
            json.dumps(
                {"type": "call", "id": "w", "tool": "chrome_watch_tab", "args": {"match": "upload"}}
            )
        )
        result = await recv_type(ws, "result")
        assert result["content"]["watching"] is True
        events.append(await recv_type(ws, "event"))
        await ws.wait_closed()

    pages = [PAGE, PAGE, dict(PAGE, progress={"bars": [{"percent": 100}]})]
    browser = FakeBrowser(TABS, {7: pages})

    async def check(server, daemon):
        while not events:
            await asyncio.sleep(0.02)
        daemon.announce("watch_done", "Second", "x", {})
        daemon.announce("watch_done", "Third", "y", {})
        await asyncio.sleep(0.3)
        assert len(daemon.outbox) == 2  # held back: one event per spacing

    asyncio.run(run_with(script, check, browser=browser, event_seconds=60))
    event = events[0]
    assert (event["event"], event["title"], event["text"]) == (
        "watch_done",
        "Upload - Example Drive is done",
        "It reached 100%.",
    )
    assert event["data"]["reason"] == "complete"


def test_a_refused_token_is_reported_as_unauthorized():
    async def handler(ws):
        await ws.close(4403, "revoked")

    async def go():
        async with serve(handler, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            daemon = make_daemon(f"ws://127.0.0.1:{port}/v1/devices/ws")
            return await daemon.run_once(TOKEN)

    assert asyncio.run(go()) == 4403


def test_close_codes_from_a_refused_handshake():
    class Response:
        status_code = 403

    class Refused(Exception):
        response = Response()

    assert close_code(Refused()) == 4401
    assert close_code(ValueError()) is None


def test_the_token_goes_in_a_header_not_the_address():
    seen = {}

    async def handler(ws):
        seen["path"] = ws.request.path
        seen["auth"] = ws.request.headers.get("Authorization")
        await ws.close()

    async def go():
        async with serve(handler, "127.0.0.1", 0) as ws_server:
            port = ws_server.sockets[0].getsockname()[1]
            ws = await websocket_connect(f"ws://127.0.0.1:{port}/v1/devices/ws", TOKEN)
            with pytest.raises(ConnectionClosed):
                await ws.recv()

    asyncio.run(go())
    assert seen == {"path": "/v1/devices/ws", "auth": f"Bearer {TOKEN}"}
