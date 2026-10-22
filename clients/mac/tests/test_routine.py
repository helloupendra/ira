"""The routine skill: readings from macOS tools, and when each observation is sent."""

from __future__ import annotations

import asyncio
import json
import plistlib

from websockets.asyncio.server import serve

from ira_mac.daemon import Daemon
from ira_mac.routine import (
    Routine,
    fingerprint,
    parse_gateway,
    parse_hardware,
    parse_idle,
    parse_locked,
)
from ira_mac.tools import Toolbox

from .conftest import FakeBrowser

# Documentation addresses only (RFC 5737, and a locally administered hardware address).
ROUTE = b"""   route to: default
destination: default
       mask: default
    gateway: 192.0.2.1
  interface: en0
"""
ARP = b"? (192.0.2.1) at 2:0:5e:a:b:c on en0 ifscope [ethernet]\n"
IOREG_IDLE = b'    |   "HIDIdleTime" = 4500000000\n'


def test_parsing_the_tools_output():
    locked = plistlib.dumps(
        {"IOConsoleUsers": [{"kCGSSessionOnConsoleKey": True, "CGSSessionScreenIsLocked": True}]}
    )
    assert parse_locked(locked) is True
    assert (
        parse_locked(plistlib.dumps({"IOConsoleUsers": [{"kCGSSessionOnConsoleKey": True}]}))
        is False
    )
    assert parse_locked(b"not a plist") is None
    assert parse_idle(IOREG_IDLE.decode()) == 4.5
    assert parse_gateway(ROUTE.decode()) == "192.0.2.1"
    assert parse_hardware(ARP.decode()) == "02:00:5e:0a:0b:0c"
    assert parse_hardware("? (192.0.2.1) at (incomplete) on en0") is None


def test_the_fingerprint_is_salted_and_carries_no_address():
    one = fingerprint("salt-a", "192.0.2.1", "02:00:5e:0a:0b:0c")
    assert len(one) == 24 and all(c in "0123456789abcdef" for c in one)
    assert one != fingerprint("salt-b", "192.0.2.1", "02:00:5e:0a:0b:0c")
    assert "192" not in one


class FakeProbe:
    def __init__(self):
        self.lock = False
        self.idle_seconds = 500.0
        self.net = ("192.0.2.1", "02:00:5e:0a:0b:0c")

    def locked(self):
        return self.lock

    def idle(self):
        return self.idle_seconds

    def network(self):
        return self.net


class Clocks:
    def __init__(self):
        self.wall = 1_792_040_000.0  # 22 Oct 2026, morning in India
        self.mono = 100.0

    def step(self, seconds, *, asleep=False):
        self.wall += seconds
        if not asleep:
            self.mono += seconds


def routine():
    probe, clocks, sent = FakeProbe(), Clocks(), []
    r = Routine(sent.append, probe, "salt", clock=lambda: clocks.wall, mono=lambda: clocks.mono)
    return r, probe, clocks, sent


def kinds(frames):
    return [f["kind"] for f in frames]


def test_lock_unlock_sleep_wake_network_and_first_activity():
    r, probe, clocks, sent = routine()
    assert kinds(r.tick()) == ["network"]  # where it is at the start; no lock change yet
    clocks.step(30)
    probe.lock = True
    assert kinds(r.tick()) == ["lock"]
    clocks.step(3600, asleep=True)  # an hour of sleep: the monotonic clock stood still
    probe.lock = False
    probe.idle_seconds = 3.0
    frames = r.tick()
    assert kinds(frames) == ["sleep", "wake", "unlock", "first_activity"]
    assert frames[0]["at"] == clocks.wall - 3600 and frames[1]["at"] == clocks.wall
    assert frames[3]["at"] == clocks.wall - 3.0
    clocks.step(30)
    assert r.tick() == []  # first activity is once a day
    probe.net = ("192.0.2.254", "02:00:5e:0a:0b:0d")
    clocks.step(30)
    frames = r.tick()
    assert kinds(frames) == ["network"] and frames[0]["network"] != sent[0]["network"]
    probe.net = None  # offline: nothing to report until a network comes back
    clocks.step(30)
    assert r.tick() == []
    assert all(f["type"] == "observe" for f in sent)


def test_off_means_nothing_is_read_or_sent():
    r, probe, clocks, sent = routine()
    calls = []
    probe.locked = lambda: calls.append("locked")

    async def go():
        r.interval = 0.01
        task = asyncio.create_task(r.run(lambda: False))
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(go())
    assert sent == [] and calls == []


def test_the_daemon_follows_skills_and_sends_queued_observations():
    received = []

    async def handler(ws):
        json.loads(await ws.recv())
        await ws.send(json.dumps({"type": "welcome", "deviceId": 1, "skills": ["chrome"]}))
        await ws.send(json.dumps({"type": "skills", "skills": ["chrome", "routine"]}))
        while True:
            frame = json.loads(await ws.recv())
            if frame.get("type") == "observe":
                received.append(frame)
                if len(received) == 2:
                    return

    async def go():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            tools = Toolbox(FakeBrowser(), lambda *a: None)
            daemon = Daemon(
                f"ws://127.0.0.1:{port}/v1/devices/ws", lambda: "irad_" + "t" * 43, tools
            )
            daemon.observe({"type": "observe", "kind": "lock", "at": 1.0, "network": None})
            task = asyncio.create_task(daemon.run_forever())
            for _ in range(200):
                if "routine" in daemon.skills:
                    break
                await asyncio.sleep(0.01)
            daemon.observe({"type": "observe", "kind": "unlock", "at": 2.0, "network": None})
            for _ in range(200):
                if len(received) == 2:
                    break
                await asyncio.sleep(0.01)
            daemon.stop()
            await asyncio.wait_for(task, 5)
            return daemon.skills

    skills = asyncio.run(go())
    assert skills == ["chrome", "routine"]
    assert [f["kind"] for f in received] == [
        "lock",
        "unlock",
    ]  # queued before connecting, then live
