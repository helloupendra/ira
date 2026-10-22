"""Reading a tab's progress, and deciding when a watched tab is done.

The Chrome extension's reader returns progress *signals*: ``<progress>`` and
ARIA bars, and text such as "63%", "Step 4/5", "ETA 4 min", "Completed". This
module turns them into one reading and a sentence, and applies the rules that
end a watch:

* the text someone asked for appears (``untilText``);
* progress reaches 100%;
* a status word that was not there at the start appears ("Completed", "Failed");
* the page has not changed for ``idleSeconds``;
* the tab closes;
* the time runs out (``timeoutMinutes``).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

DONE_WORDS = ("completed", "complete", "done", "finished", "succeeded", "success", "uploaded")
FAILED_WORDS = ("failed", "failure", "error", "cancelled", "canceled")
DEFAULT_TIMEOUT_MINUTES = 60
MAX_TIMEOUT_MINUTES = 24 * 60
MIN_IDLE_SECONDS = 10


@dataclass
class Progress:
    percent: float | None = None
    step: tuple[int, int] | None = None
    eta: str | None = None
    status: tuple[str, ...] = ()

    def sentence(self) -> str:
        parts = []
        if self.percent is not None:
            parts.append(f"{self.percent:g}%")
        if self.step is not None:
            parts.append(f"step {self.step[0]} of {self.step[1]}")
        if self.eta:
            parts.append(f"about {self.eta} left")
        if self.status:
            parts.append(" / ".join(word.capitalize() for word in self.status))
        return ", ".join(parts)

    def public(self) -> dict[str, Any]:
        return {
            "percent": self.percent,
            "step": list(self.step) if self.step else None,
            "eta": self.eta,
            "status": list(self.status),
        }


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # not NaN


def progress_of(signals: dict[str, Any] | None) -> Progress:
    """One reading from the reader's signals: bars first, then steps, then a percent in text."""
    signals = signals or {}
    percent = None
    for bar in signals.get("bars") or []:
        value = _number(bar.get("percent"))
        if value is not None:
            percent = max(0.0, min(100.0, round(value, 1)))
            break
    step = None
    for count in signals.get("counts") or []:
        done, total = count.get("done"), count.get("total")
        if isinstance(done, int) and isinstance(total, int) and 0 < total <= 1000:
            step = (min(done, total), total)
            break
    if percent is None and step is not None:
        percent = round(100 * step[0] / step[1], 1)
    if percent is None:
        for value in signals.get("percents") or []:
            number = _number(value)
            if number is not None and 0 <= number <= 100:
                percent = round(number, 1)
                break
    eta_list = signals.get("eta") or []
    eta = str(eta_list[0])[:40] if eta_list else None
    status = tuple(
        dict.fromkeys(
            str(word).lower()
            for word in signals.get("status") or []
            if str(word).lower() in DONE_WORDS + FAILED_WORDS
        )
    )
    return Progress(percent=percent, step=step, eta=eta, status=status)


def summary(title: str, progress: Progress) -> str:
    detail = progress.sentence()
    return f"{title}: {detail}" if detail else f"{title}: no progress shown"


def page_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


@dataclass
class Done:
    reason: str  # text, complete, status, idle, closed, timeout
    title: str
    text: str


@dataclass
class Watch:
    id: str
    tab_id: int
    title: str
    until_text: str | None = None
    idle_seconds: float | None = None
    timeout_minutes: float = DEFAULT_TIMEOUT_MINUTES
    started: float = field(default_factory=time.monotonic)
    first_status: tuple[str, ...] = ()
    last_hash: str | None = None
    changed_at: float | None = None
    last: Progress = field(default_factory=Progress)

    def __post_init__(self) -> None:
        self.timeout_minutes = max(1.0, min(float(self.timeout_minutes), MAX_TIMEOUT_MINUTES))
        if self.idle_seconds is not None:
            self.idle_seconds = max(float(self.idle_seconds), MIN_IDLE_SECONDS)

    def describe(self) -> str:
        """What will end this watch, in words."""
        ends = []
        if self.until_text:
            ends.append(f'"{self.until_text}" appears')
        ends.append("it reaches 100% or says it finished or failed")
        if self.idle_seconds:
            ends.append(f"nothing changes for {self.idle_seconds:g} seconds")
        ends.append("the tab closes")
        return (
            f"I'll tell you when {', or '.join(ends)} (for up to {self.timeout_minutes:g} minutes)."
        )

    def start(self, page: dict[str, Any], now: float) -> None:
        """Remember how the page looked when the watch began."""
        progress = progress_of(page.get("progress"))
        self.first_status = progress.status
        self.last = progress
        self.last_hash = page_hash(str(page.get("text", "")))
        self.changed_at = now
        self.title = str(page.get("title") or self.title)


def check(watch: Watch, page: dict[str, Any] | None, now: float) -> Done | None:
    """Whether a watch is over, given the tab's latest reading (None: the tab closed)."""
    if page is None:
        return Done("closed", f"{watch.title} was closed", "The tab closed while I watched it.")
    title = str(page.get("title") or watch.title)
    text = str(page.get("text", ""))
    progress = progress_of(page.get("progress"))
    watch.last = progress
    if watch.until_text:
        needle = watch.until_text.lower()
        if needle in text.lower() or needle in title.lower():
            return Done("text", f"{title}: done", f'"{watch.until_text}" appeared on the page.')
    if progress.percent is not None and progress.percent >= 100:
        return Done("complete", f"{title} is done", "It reached 100%.")
    new = [word for word in progress.status if word not in watch.first_status]
    if new:
        failed = [word for word in new if word in FAILED_WORDS]
        word = (failed or new)[0]
        what = "failed" if failed else "finished"
        return Done("status", f"{title} {what}", f'The page now says "{word.capitalize()}".')
    digest = page_hash(text)
    if digest != watch.last_hash:
        watch.last_hash, watch.changed_at = digest, now
    elif (
        watch.idle_seconds
        and watch.changed_at is not None
        and now - watch.changed_at >= watch.idle_seconds
    ):
        seconds = round(now - watch.changed_at)
        return Done("idle", f"{title} has gone quiet", f"Nothing changed for {seconds} seconds.")
    if now - watch.started >= watch.timeout_minutes * 60:
        last = progress.sentence()
        text = f"I stopped watching after {watch.timeout_minutes:g} minutes."
        return Done(
            "timeout", f"Stopped watching {title}", f"{text} Last seen: {last}." if last else text
        )
    return None
