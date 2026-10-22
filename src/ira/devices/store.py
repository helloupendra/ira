"""A person's devices in SQLite: pairing codes, device tokens, skills and events.

* A **pairing code** is eight characters, works once, for 10 minutes, and is
  kept only as a SHA-256 hash. A device exchanges it for its own token.
* A **device token** is ``irad_`` and 32 random bytes, shown once to the
  device. Only its hash is kept. It works on the device WebSocket only.
* A device's **skills** are the grants its user switched on ("chrome"); its
  tools are offered only while their skill is on.
* **Events** a device announced are kept seven days, 200 per person at most.
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ira.devices.protocol import KINDS, MAX_LABEL, SKILL_NAME, Event, clean_line
from ira.security import new_id, sha256_hex
from ira.store import Store

TOKEN_PREFIX = "irad_"
PAIRING_SECONDS = 600
# No 0/O or 1/I to misread.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # pragma: allowlist secret
CODE_LENGTH = 8
EVENT_SECONDS = 7 * 24 * 3600
MAX_EVENTS = 200

# The skills IRA's own clients offer, in words for the pairing and devices pages.
# A device may offer others; they show by name.
SKILLS: dict[str, str] = {
    "chrome": "Chrome: list your open tabs, read the one you ask about, and watch it "
    "until it finishes. Only when you ask.",
    "tasks": "Tasks: coding and research jobs in folders you allow. Never a push.",
    "routine": "Routine: when this Mac locks, sleeps and wakes, and which of your named "
    "networks it is on, so Ira can learn your day. Never what you do on it.",
}
DEFAULT_LABELS = {"mac": "My Mac", "android": "My Android phone"}


class DeviceError(ValueError):
    pass


@dataclass
class Device:
    id: int
    user_id: int
    kind: str
    label: str
    created_at: float
    last_seen_at: float | None = None
    revoked_at: float | None = None
    version: str | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    email: str | None = None  # the owner's, in lists for admins


@dataclass
class Pairing:
    id: str
    user_id: int
    kind: str
    label: str
    skills: list[str]
    created_at: float
    expires_at: float
    used_at: float | None = None
    device_id: int | None = None

    def state(self, now: float) -> str:
        if self.used_at is not None:
            return "paired"
        return "expired" if self.expires_at <= now else "waiting"


def _loads(text: str | None, default: Any) -> Any:
    try:
        value = json.loads(text) if text else default
    except ValueError:
        return default
    return value if isinstance(value, type(default)) else default


def _device(row: Any) -> Device:
    keys = row.keys()
    return Device(
        id=row["id"],
        user_id=row["user_id"],
        kind=row["kind"],
        label=row["label"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
        revoked_at=row["revoked_at"],
        version=row["version"],
        tools=_loads(row["tools"], []),
        skills=_loads(row["skills"], []),
        email=row["email"] if "email" in keys else None,
    )


def _pairing(row: Any) -> Pairing:
    return Pairing(
        id=row["id"],
        user_id=row["user_id"],
        kind=row["kind"],
        label=row["label"],
        skills=_loads(row["skills"], []),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        used_at=row["used_at"],
        device_id=row["device_id"],
    )


def normalise_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def show_code(code: str) -> str:
    """ABCDEFGH as ABCD-EFGH, easier to read out and type."""
    return f"{code[:4]}-{code[4:]}"


def check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise DeviceError(f"kind must be one of {', '.join(KINDS)}")
    return kind


def check_skills(skills: list[str]) -> list[str]:
    out: list[str] = []
    for skill in skills:
        if not isinstance(skill, str) or not SKILL_NAME.fullmatch(skill):
            raise DeviceError(f"unknown skill name '{skill}'")
        if skill not in out:
            out.append(skill)
    return out


def clean_label(label: str | None, kind: str) -> str:
    return clean_line(label, MAX_LABEL) or DEFAULT_LABELS.get(kind, "My device")


_ACTIVE = (
    "SELECT d.*, u.email FROM devices d JOIN users u ON u.id = d.user_id "
    "WHERE d.revoked_at IS NULL AND u.disabled_at IS NULL"
)


class Devices:
    def __init__(self, store: Store, *, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.clock = clock

    # Pairing.

    def start_pairing(
        self, user_id: int, kind: str, label: str | None, skills: list[str]
    ) -> tuple[str, Pairing]:
        """Return (code, pairing). The code is shown once; only its hash is kept."""
        kind = check_kind(kind)
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        now = self.clock()
        pairing = Pairing(
            id=new_id("pair_"),
            user_id=user_id,
            kind=kind,
            label=clean_label(label, kind),
            skills=check_skills(skills),
            created_at=now,
            expires_at=now + PAIRING_SECONDS,
        )
        self.store.execute(
            "INSERT INTO device_pairings (id, code_hash, user_id, kind, label, skills, "
            "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pairing.id,
                sha256_hex(code),
                user_id,
                kind,
                pairing.label,
                json.dumps(pairing.skills),
                now,
                pairing.expires_at,
            ),
        )
        return code, pairing

    def pairing(self, pairing_id: str) -> Pairing | None:
        row = self.store.one("SELECT * FROM device_pairings WHERE id = ?", (pairing_id,))
        return _pairing(row) if row else None

    def redeem(self, code: str, kind: str | None = None) -> tuple[str, Device] | None:
        """Exchange a pairing code for a new device and its token, once.

        None when the code is unknown, used, expired, for another kind of
        device, or its user is gone.
        """
        code = normalise_code(code)
        if len(code) != CODE_LENGTH:
            return None
        now = self.clock()
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        with self.store.transaction():
            row = self.store.one(
                "SELECT p.* FROM device_pairings p JOIN users u ON u.id = p.user_id "
                "WHERE p.code_hash = ? AND p.used_at IS NULL AND p.expires_at > ? "
                "AND u.disabled_at IS NULL",
                (sha256_hex(code), now),
            )
            if row is None or (kind is not None and row["kind"] != kind):
                return None
            cursor = self.store.execute(
                "INSERT INTO devices (user_id, kind, label, token_hash, created_at, skills) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (row["user_id"], row["kind"], row["label"], sha256_hex(token), now, row["skills"]),
            )
            device_id = int(cursor.lastrowid or 0)
            self.store.execute(
                "UPDATE device_pairings SET used_at = ?, device_id = ? WHERE id = ?",
                (now, device_id, row["id"]),
            )
        device = self.get(device_id)
        assert device is not None
        return token, device

    # Devices.

    def by_token(self, token: str) -> Device | None:
        """The active device a token belongs to; None for anything else."""
        if not token.startswith(TOKEN_PREFIX):
            return None
        row = self.store.one(_ACTIVE + " AND d.token_hash = ?", (sha256_hex(token),))
        return _device(row) if row else None

    def get(self, device_id: int, *, active: bool = True) -> Device | None:
        if active:
            row = self.store.one(_ACTIVE + " AND d.id = ?", (device_id,))
        else:
            row = self.store.one(
                "SELECT d.*, u.email FROM devices d JOIN users u ON u.id = d.user_id "
                "WHERE d.id = ?",
                (device_id,),
            )
        return _device(row) if row else None

    def for_user(self, user_id: int) -> list[Device]:
        rows = self.store.query(_ACTIVE + " AND d.user_id = ? ORDER BY d.id", (user_id,))
        return [_device(r) for r in rows]

    def everyone(self) -> list[Device]:
        rows = self.store.query(_ACTIVE + " ORDER BY u.email, d.id")
        return [_device(r) for r in rows]

    def revoke(self, device_id: int) -> bool:
        cursor = self.store.execute(
            "UPDATE devices SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (self.clock(), device_id),
        )
        return cursor.rowcount == 1

    def revoke_user(self, user_id: int) -> list[int]:
        """Revoke every device of a person (their account was removed). Returns the ids."""
        ids = [d.id for d in self.for_user(user_id)]
        self.store.execute(
            "UPDATE devices SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (self.clock(), user_id),
        )
        return ids

    def set_skills(self, device_id: int, skills: list[str]) -> None:
        self.store.execute(
            "UPDATE devices SET skills = ? WHERE id = ?",
            (json.dumps(check_skills(skills)), device_id),
        )

    def set_label(self, device_id: int, label: str, kind: str) -> str:
        cleaned = clean_label(label, kind)
        self.store.execute("UPDATE devices SET label = ? WHERE id = ?", (cleaned, device_id))
        return cleaned

    def hello(self, device_id: int, *, version: str, tools: list[dict[str, Any]]) -> None:
        """Keep what a device said in its hello: its version and its tools (never output)."""
        self.store.execute(
            "UPDATE devices SET version = ?, tools = ?, last_seen_at = ? WHERE id = ?",
            (version or None, json.dumps(tools), self.clock(), device_id),
        )

    def seen(self, device_id: int) -> None:
        self.store.execute(
            "UPDATE devices SET last_seen_at = ? WHERE id = ?", (self.clock(), device_id)
        )

    # Events.

    def add_event(self, user_id: int, device_id: int | None, event: Event) -> dict[str, Any]:
        now = self.clock()
        cursor = self.store.execute(
            "INSERT INTO device_events (user_id, device_id, at, event, title, text, data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                device_id,
                now,
                event.event,
                event.title,
                event.text,
                json.dumps(event.data, default=str),
            ),
        )
        self.store.execute(
            "DELETE FROM device_events WHERE user_id = ? AND (at < ? OR id NOT IN "
            "(SELECT id FROM device_events WHERE user_id = ? ORDER BY id DESC LIMIT ?))",
            (user_id, now - EVENT_SECONDS, user_id, MAX_EVENTS),
        )
        return self.event(int(cursor.lastrowid or 0)) or {}

    def event(self, event_id: int) -> dict[str, Any] | None:
        row = self.store.one(
            "SELECT e.id, e.at, e.event, e.title, e.text, e.data, e.device_id, d.label AS device "
            "FROM device_events e LEFT JOIN devices d ON d.id = e.device_id WHERE e.id = ?",
            (event_id,),
        )
        return _event(row) if row else None

    def events(self, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT e.id, e.at, e.event, e.title, e.text, e.data, e.device_id, d.label AS device "
            "FROM device_events e LEFT JOIN devices d ON d.id = e.device_id "
            "WHERE e.user_id = ? AND e.at >= ? ORDER BY e.id DESC LIMIT ?",
            (user_id, self.clock() - EVENT_SECONDS, limit),
        )
        return [_event(r) for r in rows]

    def clear_events(self, user_id: int) -> int:
        cursor = self.store.execute("DELETE FROM device_events WHERE user_id = ?", (user_id,))
        return cursor.rowcount


def _event(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["data"] = _loads(row["data"], {})
    return item
