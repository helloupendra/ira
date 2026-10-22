"""The routine skill: when this Mac locks, sleeps and wakes, and which network it is on.

Only while its person switched the ``routine`` skill on for this Mac. Every 30
seconds it reads:

* the screen lock, from ``ioreg`` (the console session's ``CGSSessionScreenIsLocked``);
* sleep and wake: the wall clock moves on while the Mac sleeps and the
  monotonic clock does not, so a gap between them is a sleep;
* how long since the last keyboard or mouse input (``HIDIdleTime``), for the
  first activity of the day;
* the network, as a hash of the default gateway's hardware address with a
  salt kept on this Mac. Neither the network's name nor its addresses leave
  the Mac; the person names the network on their Ira page instead.

It never reads what is on the screen, which apps run, or anything in a file.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import logging
import plistlib
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger("ira_mac.routine")

INTERVAL = 30.0
SLEEP_GAP = 90.0  # wall time ahead of monotonic time by this much: the Mac slept
ACTIVE_IDLE = 120.0  # input within this many seconds counts as activity

_IDLE = re.compile(r'"HIDIdleTime"\s*=\s*(\d+)')
_GATEWAY = re.compile(r"^\s*gateway:\s*(\S+)", re.MULTILINE)
_HARDWARE = re.compile(r"\bat\s+([0-9a-f]{1,2}(?::[0-9a-f]{1,2}){5})\b", re.IGNORECASE)


def _run(args: list[str]) -> bytes:
    return subprocess.run(args, capture_output=True, check=False, timeout=10).stdout


def parse_locked(plist: bytes) -> bool | None:
    """From ``ioreg -n Root -d1 -a``: whether the console session's screen is locked."""
    try:
        root = plistlib.loads(plist)
    except Exception:
        return None
    users = root.get("IOConsoleUsers") if isinstance(root, dict) else None
    if not users:
        return None
    for session in users:
        if session.get("kCGSSessionOnConsoleKey", True):
            return bool(session.get("CGSSessionScreenIsLocked", False))
    return None


def parse_idle(text: str) -> float | None:
    """From ``ioreg -c IOHIDSystem``: seconds since the last input."""
    match = _IDLE.search(text)
    return int(match.group(1)) / 1e9 if match else None


def parse_gateway(text: str) -> str | None:
    match = _GATEWAY.search(text)
    return match.group(1) if match else None


def parse_hardware(text: str) -> str | None:
    match = _HARDWARE.search(text)
    if not match:
        return None
    return ":".join(part.zfill(2) for part in match.group(1).lower().split(":"))


def fingerprint(salt: str, gateway: str, hardware: str) -> str:
    """A network's identity: salted, so the server can only tell networks apart."""
    return hashlib.sha256(f"{salt}|{gateway}|{hardware}".encode()).hexdigest()[:24]


class Probe(Protocol):
    def locked(self) -> bool | None: ...

    def idle(self) -> float | None: ...

    def network(self) -> tuple[str, str] | None:
        """(gateway address, its hardware address), or None when offline."""
        ...


class MacProbe:
    """Reads the real system with the tools macOS ships."""

    def locked(self) -> bool | None:
        return parse_locked(_run(["/usr/sbin/ioreg", "-n", "Root", "-d1", "-a"]))

    def idle(self) -> float | None:
        return parse_idle(_run(["/usr/sbin/ioreg", "-c", "IOHIDSystem", "-d", "4"]).decode())

    def network(self) -> tuple[str, str] | None:
        gateway = parse_gateway(_run(["/sbin/route", "-n", "get", "default"]).decode())
        if not gateway:
            return None
        hardware = parse_hardware(_run(["/usr/sbin/arp", "-n", gateway]).decode())
        return (gateway, hardware) if hardware else None


@dataclass
class Routine:
    send: Callable[[dict[str, Any]], None]
    probe: Probe
    salt: str
    clock: Callable[[], float] = time.time
    mono: Callable[[], float] = time.monotonic
    interval: float = INTERVAL
    _wall: float | None = None
    _mono: float | None = None
    _locked: bool | None = None
    _network: str | None = None
    _seen_network: bool = False
    _active_day: str | None = None

    def reset(self) -> None:
        """Forget the last reading (the skill went off): the next one starts afresh."""
        self._wall = self._mono = None
        self._locked = None
        self._network = None
        self._seen_network = False

    def _emit(self, kind: str, at: float) -> dict[str, Any]:
        frame = {"type": "observe", "kind": kind, "at": round(at, 3), "network": self._network}
        self.send(frame)
        return frame

    def tick(self) -> list[dict[str, Any]]:
        """Read once; returns the observations sent."""
        now, mono = self.clock(), self.mono()
        sent: list[dict[str, Any]] = []
        if self._wall is not None and self._mono is not None:
            gap = (now - self._wall) - (mono - self._mono)
            if gap > SLEEP_GAP:
                sent.append(self._emit("sleep", self._wall))
                sent.append(self._emit("wake", now))
        self._wall, self._mono = now, mono

        try:
            reading = self.probe.network()
        except Exception:
            reading = None
        network = fingerprint(self.salt, *reading) if reading else None
        if network != self._network or not self._seen_network:
            self._network = network
            self._seen_network = True
            if network is not None:
                sent.append(self._emit("network", now))

        try:
            locked = self.probe.locked()
        except Exception:
            locked = None
        if locked is not None and self._locked is not None and locked != self._locked:
            sent.append(self._emit("lock" if locked else "unlock", now))
        if locked is not None:
            self._locked = locked

        try:
            idle = self.probe.idle()
        except Exception:
            idle = None
        today = dt.date.fromtimestamp(now).isoformat()
        if idle is not None and idle < ACTIVE_IDLE and not locked and self._active_day != today:
            self._active_day = today
            sent.append(self._emit("first_activity", now - idle))
        return sent

    async def run(self, enabled: Callable[[], bool]) -> None:
        """Read every ``interval`` seconds while ``enabled()``; never raises."""
        was_on = False
        while True:
            on = enabled()
            if on:
                try:
                    await asyncio.to_thread(self.tick)
                except Exception:
                    log.exception("a routine reading failed")
            elif was_on:
                self.reset()
            was_on = on
            await asyncio.sleep(self.interval)
