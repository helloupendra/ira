"""The tools this Mac offers Ira: list Chrome's tabs, read one, and watch one until it is done.

All three belong to the ``chrome`` skill, which the person switches on for this
Mac on their Devices page. Reading is Tier 0; a watch is Tier 1 (small and
undoable: Ira says it is watching). Nothing here logs page text or addresses.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

from ira_mac.tabs import TabError, clean_url, match_tab
from ira_mac.watch import Watch, check, progress_of, summary

log = logging.getLogger("ira_mac.tools")

MAX_WATCHES = 5
POLL_SECONDS = 5.0
MAX_TEXT = 20_000

TAB_SELECTOR = {
    "tabId": {"type": "integer", "description": "The tab's id, from chrome_list_tabs."},
    "match": {
        "type": "string",
        "description": "Words from the tab's title or address, e.g. 'upload' or 'github'. "
        "Leave both out for the tab in front.",
    },
}

DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "chrome_list_tabs",
        "description": "List the tabs open in Chrome on this Mac: id, title, address (without "
        "its query) and which one is in front.",
        "parameters": {"type": "object", "properties": {}},
        "skill": "chrome",
        "tier": 0,
    },
    {
        "name": "chrome_read_tab",
        "description": "Read one Chrome tab: its title, address, visible text (up to 20,000 "
        "characters) and progress: percent, step, time left, Completed or Failed. Never form "
        "fields or passwords.",
        "parameters": {"type": "object", "properties": dict(TAB_SELECTOR)},
        "skill": "chrome",
        "tier": 0,
    },
    {
        "name": "chrome_watch_tab",
        "description": "Watch a Chrome tab and announce when it is done: when untilText "
        "appears, it reaches 100%, it says Completed or Failed, nothing changes for "
        "idleSeconds, or it closes. Use it when someone asks to be told when something "
        "finishes. At most 5 at once.",
        "parameters": {
            "type": "object",
            "properties": {
                **TAB_SELECTOR,
                "untilText": {"type": "string", "description": "Words to wait for on the page."},
                "idleSeconds": {
                    "type": "integer",
                    "minimum": 10,
                    "maximum": 3600,
                    "description": "Done when the page stops changing for this long.",
                },
                "timeoutMinutes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1440,
                    "description": "Give up after this long (default 60).",
                },
            },
        },
        "skill": "chrome",
        "tier": 1,
    },
]


class ToolFailed(Exception):
    """A tool could not do what was asked; the message goes back to Ira."""


class Browser(Protocol):
    async def request(self, op: str, **fields: Any) -> Any: ...


# Announces an event: (event, title, text, data).
Announce = Callable[[str, str, str, dict[str, Any]], None]


def _int(args: dict[str, Any], name: str, low: int, high: int) -> int | None:
    value = args.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolFailed(f"{name} must be a number")
    return max(low, min(int(value), high))


def _text(args: dict[str, Any], name: str) -> str | None:
    value = args.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolFailed(f"{name} must be text")
    return value.strip()[:200] or None


def _check(args: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise ToolFailed(f"unknown argument(s): {', '.join(unknown)}")


class Toolbox:
    def __init__(
        self,
        browser: Browser,
        announce: Announce,
        *,
        tasks: Any = None,
        poll_seconds: float = POLL_SECONDS,
        max_watches: int = MAX_WATCHES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.browser = browser
        self.announce = announce
        self.tasks = tasks  # a TaskRunner, when this Mac's config sets tasks up
        self.poll_seconds = poll_seconds
        self.max_watches = max_watches
        self.clock = clock
        self.watches: dict[str, tuple[Watch, asyncio.Task[None]]] = {}
        self._ids = itertools.count(1)

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return DEFINITIONS + (self.tasks.definitions if self.tasks is not None else [])

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        if not isinstance(args, dict):
            raise ToolFailed("arguments must be an object")
        if name.startswith("task_") and self.tasks is not None:
            from ira_mac.tasks import TaskError

            try:
                return await self.tasks.call(name, args)
            except TaskError as exc:
                raise ToolFailed(str(exc)) from None
        handler = {
            "chrome_list_tabs": self.list_tabs,
            "chrome_read_tab": self.read_tab,
            "chrome_watch_tab": self.watch_tab,
        }.get(name)
        if handler is None:
            raise ToolFailed(f"this Mac has no tool '{name}'")
        return await handler(args)

    # Chrome.

    async def _tabs(self) -> list[dict[str, Any]]:
        tabs = await self.browser.request("list_tabs")
        if not isinstance(tabs, list):
            raise ToolFailed("Chrome gave no tab list")
        return [t for t in tabs if isinstance(t, dict)]

    async def _read(self, tab_id: int) -> dict[str, Any]:
        page = await self.browser.request("read_tab", tabId=tab_id)
        if not isinstance(page, dict):
            raise ToolFailed("Chrome gave nothing back for that tab")
        return page

    async def _pick(self, args: dict[str, Any]) -> dict[str, Any]:
        tab_id = _int(args, "tabId", 0, 2**31)
        try:
            return match_tab(await self._tabs(), tab_id, _text(args, "match"))
        except TabError as exc:
            raise ToolFailed(str(exc)) from None

    async def list_tabs(self, args: dict[str, Any]) -> dict[str, Any]:
        _check(args, set())
        tabs = await self._tabs()
        shown = [
            {
                "id": t.get("id"),
                "title": str(t.get("title") or "")[:300],
                "url": clean_url(t.get("url")),
                "active": bool(t.get("active")),
                "window": t.get("windowId"),
            }
            for t in tabs
        ]
        front = next((t for t in tabs if t.get("active") and t.get("focused")), None)
        titles = "; ".join(t["title"] or "untitled" for t in shown[:10])
        more = f" and {len(shown) - 10} more" if len(shown) > 10 else ""
        line = f"{len(shown)} tab{'s' if len(shown) != 1 else ''} open: {titles}{more}."
        if front is not None:
            line += f" In front: {front.get('title') or 'untitled'}."
        log.info("listed %d tabs", len(shown))
        return {"tabs": shown, "summary": line}

    async def read_tab(self, args: dict[str, Any]) -> dict[str, Any]:
        _check(args, {"tabId", "match"})
        tab = await self._pick(args)
        page = await self._read(int(tab["id"]))
        title = str(page.get("title") or tab.get("title") or "untitled")[:300]
        progress = progress_of(page.get("progress"))
        text = str(page.get("text") or "")[:MAX_TEXT]
        log.info("read tab %s", tab.get("id"))
        return {
            "tab": {"id": tab.get("id"), "title": title, "url": clean_url(page.get("url"))},
            "summary": summary(title, progress),
            "progress": progress.public(),
            "text": text,
            "truncated": bool(page.get("truncated")) or len(str(page.get("text") or "")) > MAX_TEXT,
        }

    async def watch_tab(self, args: dict[str, Any]) -> dict[str, Any]:
        _check(args, {"tabId", "match", "untilText", "idleSeconds", "timeoutMinutes"})
        if len(self.watches) >= self.max_watches:
            raise ToolFailed(
                f"I am already watching {self.max_watches} tabs; that is the most at once"
            )
        tab = await self._pick(args)
        watch = Watch(
            id=f"w{next(self._ids)}",
            tab_id=int(tab["id"]),
            title=str(tab.get("title") or "the tab"),
            until_text=_text(args, "untilText"),
            idle_seconds=_int(args, "idleSeconds", 10, 3600),
            timeout_minutes=_int(args, "timeoutMinutes", 1, 1440) or 60,
            started=self.clock(),
        )
        page = await self._read(watch.tab_id)
        now = self.clock()
        watch.start(page, now)
        done = check(watch, page, now)
        tab_view = {"id": watch.tab_id, "title": watch.title, "url": clean_url(page.get("url"))}
        if done is not None and done.reason in ("text", "complete"):
            return {"watching": False, "tab": tab_view, "summary": f"{done.title}. {done.text}"}
        task = asyncio.create_task(self._watch(watch))
        self.watches[watch.id] = (watch, task)
        log.info("watching tab %s as %s", watch.tab_id, watch.id)
        return {
            "watching": True,
            "watchId": watch.id,
            "tab": tab_view,
            "summary": f"Watching {watch.title}. Now: {summary(watch.title, watch.last)}. "
            + watch.describe(),
        }

    async def _watch(self, watch: Watch) -> None:
        failures = 0
        try:
            while True:
                await asyncio.sleep(self.poll_seconds)
                now = self.clock()
                try:
                    page: dict[str, Any] | None = await self._read(watch.tab_id)
                    failures = 0
                except Exception as exc:
                    if "no tab" in str(exc).lower():
                        page = None  # the tab closed
                    else:
                        failures += 1  # Chrome busy or reconnecting: try again
                        if failures % 12 == 1:
                            log.warning("watch %s: Chrome did not answer", watch.id)
                        if now - watch.started < watch.timeout_minutes * 60:
                            continue
                        page = {"title": watch.title, "text": "", "progress": {}}
                done = check(watch, page, now)
                if done is not None:
                    minutes = (now - watch.started) / 60
                    log.info("watch %s ended: %s after %.1f min", watch.id, done.reason, minutes)
                    self.announce(
                        "watch_done",
                        done.title,
                        done.text,
                        {"tabId": watch.tab_id, "watchId": watch.id, "reason": done.reason},
                    )
                    return
        finally:
            self.watches.pop(watch.id, None)

    async def stop(self) -> None:
        for _, task in list(self.watches.values()):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
