"""Chrome to the daemon: the host relay and the bridge's Unix socket, end to end; and the tools."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import threading
from pathlib import Path

import pytest

from ira_mac.bridge import BridgeError, ChromeBridge
from ira_mac.frames import read_frame, write_frame
from ira_mac.host import Relay
from ira_mac.tools import Toolbox, ToolFailed

from .conftest import FakeBrowser


@pytest.fixture
def short_dir():
    # Unix socket paths are limited to about 104 bytes on macOS: keep it short.
    folder = tempfile.mkdtemp(prefix="iram", dir="/tmp")
    yield Path(folder)
    shutil.rmtree(folder, ignore_errors=True)


def fake_extension(chrome_in, chrome_out, tabs):
    """Chrome and the extension: reads requests the host relays, answers them."""
    with os.fdopen(chrome_out, "rb") as requests, os.fdopen(chrome_in, "wb") as replies:
        write_frame(replies, {"type": "hello", "extension": "0.3.0"})
        while True:
            message = read_frame(requests)
            if message is None:
                return
            if message.get("type") == "status":
                continue
            if message["op"] == "list_tabs":
                write_frame(replies, {"id": message["id"], "ok": True, "result": tabs})
            else:
                write_frame(
                    replies, {"id": message["id"], "ok": False, "error": "No tab with id 9"}
                )


def test_a_request_travels_through_the_host_to_chrome_and_back(short_dir):
    socket_path = short_dir / "run" / "chrome.sock"
    tabs = [{"id": 1, "title": "Upload", "url": "https://drive.example.com/"}]
    # Two pipes stand in for the host's stdin and stdout, which Chrome holds.
    host_in_read, host_in_write = os.pipe()
    host_out_read, host_out_write = os.pipe()

    async def go():
        bridge = ChromeBridge(socket_path, request_seconds=3)
        relay = Relay(
            socket_path,
            os.fdopen(host_in_read, "rb"),
            os.fdopen(host_out_write, "wb"),
            retry_seconds=0.05,
        )
        threading.Thread(target=relay.run, daemon=True).start()  # starts before the daemon
        extension = threading.Thread(
            target=fake_extension, args=(host_in_write, host_out_read, tabs), daemon=True
        )
        extension.start()
        with pytest.raises(BridgeError, match="Chrome is not connected"):
            await bridge.request("list_tabs")
        await bridge.start()
        assert oct(socket_path.parent.stat().st_mode & 0o777) == "0o700"
        for _ in range(100):
            if bridge.connected and bridge.extension_version:
                break
            await asyncio.sleep(0.05)
        assert bridge.extension_version == "0.3.0"
        listed = await bridge.request("list_tabs")
        with pytest.raises(BridgeError, match="No tab with id 9"):
            await bridge.request("read_tab", tabId=9)
        await bridge.stop()
        relay.done.set()
        return listed

    assert asyncio.run(go()) == tabs
    assert not socket_path.exists()


def test_a_bridge_request_times_out(short_dir):
    async def go():
        bridge = ChromeBridge(short_dir / "c.sock", request_seconds=0.2)
        await bridge.start()
        reader, writer = await asyncio.open_unix_connection(str(short_dir / "c.sock"))
        await asyncio.sleep(0.05)  # connected, but this "Chrome" never answers
        try:
            with pytest.raises(BridgeError, match="did not answer within 0.2 seconds"):
                await bridge.request("list_tabs")
        finally:
            writer.close()
            await bridge.stop()

    asyncio.run(go())


TABS = [
    {
        "id": 1,
        "title": "Inbox",
        "url": "https://mail.example.com/",
        "active": False,
        "focused": True,
    },
    {
        "id": 2,
        "title": "Upload - Drive",
        "url": "https://drive.example.com/up?x=1",
        "active": True,
        "focused": True,
    },
]


def test_list_and_read():
    page = {
        "title": "Upload - Drive",
        "url": "https://drive.example.com/up",
        "text": "t",
        "progress": {"percents": [63]},
    }
    tools = Toolbox(FakeBrowser(TABS, {2: page}), lambda *a: None)
    listed = asyncio.run(tools.call("chrome_list_tabs", {}))
    assert listed["summary"] == "2 tabs open: Inbox; Upload - Drive. In front: Upload - Drive."
    assert listed["tabs"][1]["url"] == "https://drive.example.com/up"
    read = asyncio.run(tools.call("chrome_read_tab", {}))
    assert read["summary"] == "Upload - Drive: 63%"
    with pytest.raises(ToolFailed, match="unknown argument"):
        asyncio.run(tools.call("chrome_read_tab", {"url": "x"}))
    with pytest.raises(ToolFailed, match="no tab matches"):
        asyncio.run(tools.call("chrome_read_tab", {"match": "weather"}))


def test_at_most_five_watches_and_a_closed_tab_ends_one():
    events = []
    pages = {2: {"title": "Upload - Drive", "text": "t", "progress": {"percents": [10]}}}
    browser = FakeBrowser(TABS, pages)

    async def go():
        tools = Toolbox(browser, lambda *e: events.append(e), poll_seconds=0.05, max_watches=5)
        for _ in range(5):
            started = await tools.call("chrome_watch_tab", {"tabId": 2})
            assert started["watching"] is True
        with pytest.raises(ToolFailed, match="already watching 5 tabs"):
            await tools.call("chrome_watch_tab", {"tabId": 2})
        del pages[2]  # the tab closes
        for _ in range(100):
            if len(events) == 5:
                break
            await asyncio.sleep(0.02)
        assert tools.watches == {}
        await tools.stop()

    asyncio.run(go())
    assert {e[3]["reason"] for e in events} == {"closed"}
    assert events[0][1] == "Upload - Drive was closed"


def test_a_tab_already_done_is_reported_without_a_watch():
    page = {"title": "Upload - Drive", "text": "t", "progress": {"bars": [{"percent": 100}]}}
    tools = Toolbox(FakeBrowser(TABS, {2: page}), lambda *a: None)
    result = asyncio.run(tools.call("chrome_watch_tab", {"match": "upload"}))
    assert result["watching"] is False and "It reached 100%" in result["summary"]
    assert tools.watches == {}
