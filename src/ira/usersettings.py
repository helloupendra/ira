"""Each person's own preferences, kept in ``user_settings`` on top of ``ira.yaml``.

* ``assistant_name``: what this person calls the assistant (default: the
  installation's name);
* ``wake_phrase``: what their phone listens for (default "Hey Ira");
* ``languages``: the languages they speak to it in;
* ``reply_language``: ``auto`` (the language they spoke) or a fixed one;
* ``web_search``: whether web and news search are on for them. Off until
  they switch it on, with their PIN.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import dataclass, field
from typing import Any

from ira.store import Store

LANGUAGES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "hinglish": "Hinglish",
}
REPLY_LANGUAGES = ("auto", *LANGUAGES)
DEFAULT_LANGUAGES = ("hinglish", "en", "hi")
DEFAULT_WAKE_PHRASE = "Hey Ira"
# Where learning may come from; each is switched on by the person. A Mac is switched
# on per device, with its "routine" skill.
LEARNING_SOURCES = ("phone", "conversation", "feedback")
MIN_LEARNING_DAYS = 14
MAX_LEARNING_DAYS = 365
MAX_NAME = 32
MAX_WAKE_PHRASE = 40


class SettingsError(ValueError):
    pass


@dataclass
class Prefs:
    assistant_name: str | None = None  # None: the installation's name
    wake_phrase: str = DEFAULT_WAKE_PHRASE
    languages: list[str] = field(default_factory=lambda: list(DEFAULT_LANGUAGES))
    reply_language: str = "auto"
    web_search: bool = False
    # Learning: off until switched on; each source on its own; kept learning_days.
    learning: bool = False
    learning_sources: list[str] = field(default_factory=list)
    learning_days: int = 90
    nudges: bool = False
    timezone: str | None = None  # an IANA name, such as Asia/Kolkata; None: the server's
    approval_minutes: int | None = None  # None: the server's actions.approval_minutes


def clean_name(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit]


def today_for(prefs: Prefs) -> dt.date:
    """Today in the person's own time zone, else the server's."""
    return now_for(prefs).date()


def now_for(prefs: Prefs, epoch: float | None = None) -> dt.datetime:
    """Now in the person's own time zone, else the server's, as an aware time."""
    from zoneinfo import ZoneInfo

    moment = dt.datetime.fromtimestamp(time.time() if epoch is None else epoch, dt.UTC)
    if prefs.timezone and valid_timezone(prefs.timezone):
        return moment.astimezone(ZoneInfo(prefs.timezone))
    return moment.astimezone()


def valid_timezone(name: str) -> bool:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    if not name or "/" not in name and name != "UTC":
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def check_languages(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        code = value.strip().lower()
        if code not in LANGUAGES:
            raise SettingsError(f"unknown language '{value}'; choose from {', '.join(LANGUAGES)}")
        if code not in seen:
            seen.append(code)
    if not seen:
        raise SettingsError("choose at least one language")
    return seen


def check_reply_language(value: str) -> str:
    code = value.strip().lower()
    if code not in REPLY_LANGUAGES:
        raise SettingsError(f"reply language must be one of {', '.join(REPLY_LANGUAGES)}")
    return code


class UserSettings:
    def __init__(
        self,
        store: Store,
        *,
        languages: list[str] | None = None,
        reply_language: str = "auto",
    ) -> None:
        self.store = store
        self.default_languages = list(languages or DEFAULT_LANGUAGES)
        self.default_reply_language = reply_language

    def _raw(self, user_id: int) -> dict[str, Any]:
        rows = self.store.query(
            "SELECT key, value FROM user_settings WHERE user_id = ?", (user_id,)
        )
        out: dict[str, Any] = {}
        for row in rows:
            try:
                out[row["key"]] = json.loads(row["value"])
            except ValueError:
                continue
        return out

    def get(self, user_id: int | None) -> Prefs:
        prefs = Prefs(
            languages=list(self.default_languages), reply_language=self.default_reply_language
        )
        if user_id is None:
            return prefs
        raw = self._raw(user_id)
        if isinstance(raw.get("assistant_name"), str) and raw["assistant_name"].strip():
            prefs.assistant_name = raw["assistant_name"]
        if isinstance(raw.get("wake_phrase"), str) and raw["wake_phrase"].strip():
            prefs.wake_phrase = raw["wake_phrase"]
        if isinstance(raw.get("languages"), list):
            try:
                prefs.languages = check_languages([str(v) for v in raw["languages"]])
            except SettingsError:
                pass
        if raw.get("reply_language") in REPLY_LANGUAGES:
            prefs.reply_language = raw["reply_language"]
        prefs.web_search = raw.get("web_search") is True
        prefs.learning = raw.get("learning") is True
        sources = raw.get("learning_sources")
        if isinstance(sources, list):
            prefs.learning_sources = [s for s in sources if s in LEARNING_SOURCES]
        days = raw.get("learning_days")
        if isinstance(days, int) and MIN_LEARNING_DAYS <= days <= MAX_LEARNING_DAYS:
            prefs.learning_days = days
        prefs.nudges = raw.get("nudges") is True
        if isinstance(raw.get("timezone"), str) and valid_timezone(raw["timezone"]):
            prefs.timezone = raw["timezone"]
        minutes = raw.get("approval_minutes")
        if isinstance(minutes, int) and (minutes == 0 or 5 <= minutes <= 60):
            prefs.approval_minutes = minutes
        return prefs

    def overridden(self, user_id: int) -> set[str]:
        return set(self._raw(user_id))

    def set(self, user_id: int, key: str, value: Any) -> None:
        """Store one preference; ``None`` goes back to the default."""
        if value is None:
            self.store.execute(
                "DELETE FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key)
            )
            return
        self.store.execute(
            "INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
            (user_id, key, json.dumps(value, ensure_ascii=False)),
        )

    def delete_all(self, user_id: int) -> None:
        self.store.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))


LANGUAGE_WORDS = {
    "en": "English",
    "hi": "Hindi (in Devanagari or in Latin letters)",
    "hinglish": "Hinglish (Hindi and English mixed in one sentence)",
}
REPLY_RULES = {
    "auto": "Reply in the language and script of their latest message, not of earlier "
    "messages or tool results: English gets English; Hindi in Devanagari gets Hindi in "
    "Devanagari; Hindi or Hinglish in Latin letters gets Hinglish in Latin letters. Keep "
    "names, titles and addresses as they are.",
    "en": "Always reply in English.",
    "hi": "Always reply in Hindi, in Devanagari.",
    "hinglish": "Always reply in Hinglish, in Latin letters.",
}


def language_rule(prefs: Prefs) -> str:
    """The system prompt's lines about languages, for this person."""
    words = [LANGUAGE_WORDS[code] for code in prefs.languages if code in LANGUAGE_WORDS]
    if len(words) > 1:
        spoken = ", ".join(words[:-1]) + " or " + words[-1]
    else:
        spoken = words[0] if words else "English"
    return (
        f"- People may speak to you in {spoken}, often in half sentences. Work out what they "
        'mean. If a tool that only reads can settle it ("upload kitna hua": look at their '
        "tabs), look first; ask one short question back only when looking would not help.\n"
        f"- {REPLY_RULES.get(prefs.reply_language, REPLY_RULES['auto'])} Never answer in "
        "any other language or script, such as Chinese, even if the message is garbled."
    )
