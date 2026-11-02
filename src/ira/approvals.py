"""Approval windows: one PIN on a screen-control action lets the next steps on that device
run without asking, for a few minutes (docs/security.md, "Approvals").

A window belongs to one person and one device. Only a PIN on a confirm card opens or
renews it; anyone it belongs to, or their device, may stop it. It never covers what is on
the never-list: sending, calling, paying, deleting, pushing, or a new grant.
"""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ira.store import Store

COVERED_SKILLS = frozenset({"screen", "control"})
COVERED_TOOLS = frozenset(
    {"app_open", "url_open", "media_play", "media_control", "settings_toggle"}
)
# Never covered, whatever the skill: a name that says it sends, calls, pays, deletes...
NEVER = re.compile(
    r"(^|_)(send|reply|call|place|pay|payment|buy|transfer|delete|remove|push|grant|pair)(_|$)"
)
MINUTES_CHOICES = (0, 5, 10, 15, 20, 30, 45, 60)
# What the person may take off the lists below, per device, with their PIN. Password managers and
# Ira's own windows are on no list here: the devices refuse those whatever is unlocked.
UNLOCKABLE = frozenset({"terminals", "editors"})
NOTHING_UNLOCKED: frozenset[str] = frozenset()
# Inside a window too, these ask every time: money, and what cannot be undone.
RISKY_WORDS = re.compile(
    r"\b(pay|payment|buy|purchase|checkout|check out|place order|order now|transfer|send money|"
    r"upi|delete|erase|empty trash|move to trash|move to bin)\b"
    r"|भुगतान|ख़रीद|खरीद|हटाओ|डिलीट|मिटाओ|पेमेंट",
    re.IGNORECASE,
)
RISKY_PLACES = re.compile(
    r"\b(bank|banking|netbanking|paypal|razorpay|paytm|phonepe|gpay|stripe|checkout|wallet|"
    r"payment|payments)\b|बैंक",
    re.IGNORECASE,
)
RISKY_KEYS = re.compile(r"(cmd|command)\+(shift\+)?(delete|backspace|forwarddelete)", re.IGNORECASE)
# Apps Ira never acts in, by name or bundle id: whatever is typed there runs as a command.
NEVER_APPS = (
    "terminal", "iterm", "script editor", "scripteditor", "automator", "termux",
    # Shortcuts can be given a "Run Shell Script" step by typing and clicking.
    "shortcuts",
    # Windows: its shells, the tools that change the system itself, and Task Manager, whose
    # "Run new task" runs a command.
    "powershell", "command prompt", "registry editor", "regedit", "windows subsystem for linux",
    "task manager", "taskmgr",
)  # fmt: skip
NEVER_IDS = frozenset(
    {"com.apple.terminal", "com.googlecode.iterm2", "com.apple.scripteditor2",
     "com.apple.automator", "dev.warp.warp-stable", "com.mitchellh.ghostty",
     "net.kovidgoyal.kitty", "org.alacritty", "com.termux", "com.apple.shortcuts",
     "com.github.wez.wezterm", "co.zeit.hyper", "org.tabby",
     # Windows programs, as Ira for Windows names the app in front (its program file).
     "cmd", "cmd.exe", "powershell.exe", "pwsh", "pwsh.exe", "wt", "wt.exe",
     "windowsterminal.exe", "openconsole.exe", "conhost.exe", "wsl", "wsl.exe", "bash.exe",
     "regedit.exe", "mmc.exe", "microsoft.windowsterminal_8wekyb3d8bbwe!app",
     "taskmgr.exe", "wscript.exe", "cscript.exe", "mshta.exe"}
)  # fmt: skip
# Apps Ira may open but never types, clicks or presses keys in: code editors with a terminal
# of their own (ctrl+` opens it), File Explorer and its Run box (their address bar runs what
# is typed), and Python's and Node's own windows.
NEVER_TYPE_WORDS = (
    "visual studio code", "vscodium", "intellij", "pycharm", "webstorm", "phpstorm", "goland",
    "rubymine", "clion", "android studio",
)  # fmt: skip
NEVER_TYPE_IDS = frozenset(
    {"com.microsoft.vscode", "com.microsoft.vscodeinsiders", "com.vscodium",
     "com.todesktop.230313mzl4w4u92", "com.exafunction.windsurf", "dev.zed.zed",
     "dev.zed.zed-preview", "com.panic.nova", "com.google.android.studio",
     "explorer", "explorer.exe", "file explorer", "run", "code", "code.exe",
     "code - insiders.exe", "cursor", "cursor.exe", "windsurf", "windsurf.exe", "zed", "zed.exe",
     "nova", "idea64.exe", "pycharm64.exe", "webstorm64.exe", "phpstorm64.exe", "goland64.exe",
     "rubymine64.exe", "clion64.exe", "rider64.exe", "studio64.exe", "python", "python.exe",
     "pythonw.exe", "py.exe", "idle", "node", "node.exe", "powershell_ise.exe"}
)  # fmt: skip
# Whole families, by the start of their bundle id: JetBrains' editors all have a terminal.
NEVER_TYPE_PREFIXES = ("com.jetbrains.",)

# Files that run something when opened, on a Mac or a PC: file_open never opens them, and an
# app on the never list is not opened as a file either (Terminal.app).
RUNNABLE = frozenset(
    {"command", "tool", "terminal", "sh", "zsh", "bash", "csh", "fish", "workflow", "action",
     "scpt", "scptd", "applescript", "osascript", "pkg", "mpkg", "shortcut", "webloc", "inetloc",
     "fileloc", "mobileconfig", "jar", "py", "pyw", "rb", "pl", "js", "jse", "vbs", "vbe", "wsf",
     "wsh", "hta", "exe", "com", "bat", "cmd", "ps1", "psm1", "msi", "msc", "cpl", "scr", "pif",
     "lnk", "url", "reg", "inf", "appref-ms", "settingcontent-ms", "library-ms", "search-ms"}
)  # fmt: skip

NEVER_OPEN_REFUSAL = (
    "refused: Ira never opens Terminal, PowerShell, Task Manager, Shortcuts or the like, nor a "
    "file that runs something when opened. Tell the person to do it themselves."
)


URL_REFUSAL = "refused: Ira opens only web addresses (https://...), never a file or an app's link."


def open_refusal(
    tool: str, arguments: dict[str, object], unlocked: frozenset[str] = NOTHING_UNLOCKED
) -> str | None:
    """Why a device must not open this, or None. The devices refuse these too; this is the
    server's own check, so an older app or a server-side mistake cannot get round them."""
    if tool == "app_open":
        named = [arguments.get(key) for key in ("name", "package", "app")]
        if any(isinstance(value, str) and never_app(value, unlocked) for value in named):
            return NEVER_OPEN_REFUSAL
    if tool == "file_open" and isinstance(arguments.get("path"), str):
        # Windows drops trailing dots and spaces, so "run.bat. " opens as run.bat.
        name = str(arguments["path"]).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].rstrip(". ")
        stem, dot, extension = name.rpartition(".")
        extension = extension.lower() if dot else ""
        if extension in RUNNABLE or (extension == "app" and never_app(stem)):
            return NEVER_OPEN_REFUSAL
    if tool == "url_open" and isinstance(arguments.get("url"), str):
        address = str(arguments["url"]).strip()
        if "://" in address and address.split("://", 1)[0].lower() not in ("http", "https"):
            return URL_REFUSAL
    return None


def risky_step(tool: str, arguments: dict[str, Any], looked: dict[str, Any] | None) -> str | None:
    """Why this step needs its own yes inside an approval, or None. `looked`: what the last look
    at that device's window showed, so a click by id is read by its label."""
    looked = looked or {}
    shown = (looked.get("elements") or {}).get(str(arguments.get("id") or ""))
    said = " ".join(str(arguments.get(key) or "") for key in ("label", "path")) + f" {shown or ''}"
    if RISKY_WORDS.search(said):
        return f"it may pay or delete: {said.strip()[:80]}"
    if RISKY_KEYS.search(str(arguments.get("keys") or "")):
        return "those keys delete a file"
    place = " ".join(str(looked.get(key) or "") for key in ("appName", "window"))
    if RISKY_PLACES.search(f"{place} {arguments.get('url') or ''} {arguments.get('app') or ''}"):
        return f"a banking or payment place: {place.strip()[:80]}"
    return None


def never_app(app: str | None, unlocked: frozenset[str] = NOTHING_UNLOCKED) -> bool:
    """Terminal, iTerm, Script Editor, Automator, and on Windows the Command Prompt, PowerShell,
    Windows Terminal and the Registry Editor: never acted in, never trusted.

    Names match by any part ("terminal" anywhere in it): an app that merely has such a word
    in its name is refused too. That errs on the safe side on purpose; do not narrow it
    to exact names without weighing that."""
    if not app or "terminals" in unlocked:
        return False
    name = app.strip().lower().removesuffix(".app")
    return name in NEVER_IDS or any(word in name for word in NEVER_APPS)


def never_type(app: str | None, unlocked: frozenset[str] = NOTHING_UNLOCKED) -> bool:
    """Whether Ira must never type, click or press keys in this app, nor trust it: the
    never-list, and the apps that may be opened but run what is typed in them (an
    editor's terminal, Explorer's address bar)."""
    if not app:
        return False
    name = app.strip().lower().removesuffix(".app")
    if never_app(app, unlocked):
        return True
    if "editors" in unlocked:
        return False
    return (
        name in NEVER_TYPE_IDS
        or name.startswith(NEVER_TYPE_PREFIXES)
        or any(word in name for word in NEVER_TYPE_WORDS)
    )


# An app as a device names it: an Android package or a macOS bundle id.
APP_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_-]+){1,8}")


def covered(tool: str, skill: str | None) -> bool:
    """Whether an approval window may run this tool without asking."""
    if NEVER.search(tool):
        return False
    return tool in COVERED_TOOLS or (skill or "") in COVERED_SKILLS


def valid_minutes(minutes: int) -> bool:
    return minutes == 0 or 5 <= minutes <= 60


@dataclass
class Window:
    id: str
    user_id: int
    device_id: int
    opened_at: float
    expires_at: float
    steps: int


def _window(row: Any) -> Window:
    return Window(
        id=row["id"],
        user_id=row["user_id"],
        device_id=row["device_id"],
        opened_at=row["opened_at"],
        expires_at=row["expires_at"],
        steps=row["steps"],
    )


class Approvals:
    def __init__(
        self,
        store: Store,
        *,
        minutes_for: Callable[[int], int],
        connected: Callable[[int], bool],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.minutes_for = minutes_for
        self.connected = connected
        self.clock = clock

    def open(
        self, user_id: int, device_id: int, action_id: str | None = None, minutes: int | None = None
    ) -> Window | None:
        """A PIN confirmed a covered action on this device, or the person asked for this many
        minutes with their PIN: open the window, or start it again from now. None when the
        person switched approvals off and asked for no length."""
        minutes = self.minutes_for(user_id) if minutes is None else minutes
        if minutes <= 0:
            return None
        now = self.clock()
        current = self.active(user_id, device_id)
        if current is not None:
            self.store.execute(
                "UPDATE approval_windows SET expires_at = ? WHERE id = ?",
                (now + minutes * 60, current.id),
            )
            current.expires_at = now + minutes * 60
            return current
        window_id = "apw_" + secrets.token_hex(6)
        self.store.execute(
            "INSERT INTO approval_windows (id, user_id, device_id, opened_at, expires_at, "
            "opened_by) VALUES (?, ?, ?, ?, ?, ?)",
            (window_id, user_id, device_id, now, now + minutes * 60, action_id),
        )
        return self.get(window_id)

    def get(self, window_id: str) -> Window | None:
        row = self.store.one("SELECT * FROM approval_windows WHERE id = ?", (window_id,))
        return _window(row) if row else None

    def active(self, user_id: int, device_id: int) -> Window | None:
        """The open window for this person on this device; it ends when the device is gone."""
        row = self.store.one(
            "SELECT * FROM approval_windows WHERE user_id = ? AND device_id = ? "
            "AND closed_at IS NULL AND expires_at > ? ORDER BY opened_at DESC, rowid DESC LIMIT 1",
            (user_id, device_id, self.clock()),
        )
        if row is None:
            return None
        if not self.connected(device_id):
            self._close("device_id = ? AND user_id = ?", (device_id, user_id), "disconnected")
            return None
        return _window(row)

    def for_user(self, user_id: int) -> list[Window]:
        rows = self.store.query(
            "SELECT * FROM approval_windows WHERE user_id = ? AND closed_at IS NULL "
            "AND expires_at > ? ORDER BY opened_at",
            (user_id, self.clock()),
        )
        return [w for w in map(_window, rows) if self.active(user_id, w.device_id) is not None]

    def covers(self, user_id: int | None, device_id: int | None, tool: str, skill: str | None):
        """The window that lets this tool run now, or None."""
        if user_id is None or device_id is None or not covered(tool, skill):
            return None
        return self.active(user_id, device_id)

    def step(self, window: Window) -> None:
        self.store.execute(
            "UPDATE approval_windows SET steps = steps + 1 WHERE id = ?", (window.id,)
        )

    def stop(self, user_id: int, window_id: str | None = None) -> int:
        """Stop one window of this person's, or all of them. Returns how many stopped."""
        if window_id is None:
            return self._close("user_id = ?", (user_id,), "stopped")
        return self._close("user_id = ? AND id = ?", (user_id, window_id), "stopped")

    def end_for_device(self, device_id: int, why: str = "device removed") -> None:
        self._close("device_id = ?", (device_id,), why)

    def _close(self, where: str, params: tuple[Any, ...], why: str) -> int:
        cursor = self.store.execute(
            f"UPDATE approval_windows SET closed_at = ?, closed_why = ? "
            f"WHERE {where} AND closed_at IS NULL AND expires_at > ?",
            (self.clock(), why, *params, self.clock()),
        )
        return cursor.rowcount

    # What the person took off the never-lists on a device, with their PIN.

    def unlocked(self, user_id: int, device_id: int) -> frozenset[str]:
        rows = self.store.query(
            "SELECT grp FROM control_unlocked WHERE user_id = ? AND device_id = ?",
            (user_id, device_id),
        )
        return frozenset(r["grp"] for r in rows)

    def set_unlocked(self, user_id: int, device_id: int, groups: list[str]) -> frozenset[str]:
        clean = {g for g in groups if g in UNLOCKABLE}
        with self.store.transaction():
            self.store.execute(
                "DELETE FROM control_unlocked WHERE user_id = ? AND device_id = ?",
                (user_id, device_id),
            )
            for group in sorted(clean):
                self.store.execute(
                    "INSERT INTO control_unlocked (user_id, device_id, grp, added_at) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, device_id, group, self.clock()),
                )
        return frozenset(clean)

    # Trusted apps: screen control there runs without asking, while the app is in front.

    def trusted(self, user_id: int, device_id: int) -> set[str]:
        rows = self.store.query(
            "SELECT app FROM trusted_apps WHERE user_id = ? AND device_id = ?",
            (user_id, device_id),
        )
        return {r["app"] for r in rows}

    def trusted_by_device(self, user_id: int) -> dict[int, list[str]]:
        rows = self.store.query(
            "SELECT device_id, app FROM trusted_apps WHERE user_id = ? ORDER BY device_id, app",
            (user_id,),
        )
        found: dict[int, list[str]] = {}
        for row in rows:
            found.setdefault(row["device_id"], []).append(row["app"])
        return found

    def set_trusted(self, user_id: int, device_id: int, apps: list[str]) -> list[str]:
        # A Windows program file is named in any case and reported in lower case.
        named = [
            a.strip().lower() if a.strip().lower().endswith(".exe") else a.strip() for a in apps
        ]
        clean = sorted({a for a in named if APP_ID.fullmatch(a) and not never_type(a)})
        with self.store.transaction():
            self.store.execute(
                "DELETE FROM trusted_apps WHERE user_id = ? AND device_id = ?",
                (user_id, device_id),
            )
            for app in clean:
                self.store.execute(
                    "INSERT INTO trusted_apps (user_id, device_id, app, added_at) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, device_id, app, self.clock()),
                )
        return clean

    def trusts(
        self, user_id: int | None, device_id: int | None, front: str | None, tool: str,
        skill: str | None,
    ) -> bool:  # fmt: skip
        """Whether a screen action may run at once because the app in front is trusted."""
        if user_id is None or device_id is None or not front:
            return False
        if (skill or "") not in COVERED_SKILLS or not covered(tool, skill):
            return False
        return self.connected(device_id) and front in self.trusted(user_id, device_id)

    def prompt_lines(self, user_id: int | None, label: Callable[[int], str]) -> list[str]:
        if user_id is None:
            return []
        lines = []
        for window in self.for_user(user_id):
            left = max(1, round((window.expires_at - self.clock()) / 60))
            lines.append(f"{label(window.device_id)}: for about {left} more minutes")
        return lines
