"""Which of the person's devices a sentence names, in any script, as speech-to-text writes it.

A device the person names is the device they mean: other devices' tools are not on offer for that
turn, whatever the model would like. So this errs on the side of a brand or a kind said outright;
"phone" counts only as a place ("phone par", "on my phone"), never in "phone number".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_DEVANAGARI = "ऀ-ॿ"


@dataclass(frozen=True)
class Roster:
    """One device of a person's, as a turn sees it."""

    id: int
    label: str
    kind: str
    connected: bool
    skills: tuple[str, ...] = field(default_factory=tuple)


# What a kind of device is called. "laptop" and "computer" are whichever computer they have.
_KIND_WORDS: dict[str, tuple[str, ...]] = {
    "mac": (
        "mac", "macbook", "mac book", "imac", "mac mini", "laptop", "computer",
        "मैक", "मैकबुक", "मैक बुक", "मेकबुक", "मेक बुक", "लैपटॉप", "कंप्यूटर", "कम्प्यूटर",
    ),
    "windows": (
        "pc", "windows", "laptop", "computer", "विंडोज", "लैपटॉप", "कंप्यूटर", "कम्प्यूटर",
    ),
    "ios": ("iphone", "i phone", "ipad", "आईफोन", "आई फोन", "आईफ़ोन", "आई फ़ोन", "आईपैड"),
    "android": (
        "android", "pixel", "samsung", "galaxy", "oneplus", "redmi",
        "एंड्रॉयड", "एंड्रॉइड", "पिक्सल", "पिक्सेल", "सैमसंग",
    ),
}  # fmt: skip
_PHONE_KINDS = ("ios", "android")
_NOT_A_NAME = {"my", "the", "phone", "mobile", "ira", "and", "for", "ios", "android", "mac", "ka"}
# "phone" as a place, not "Avery ka phone number" nor "phone call".
_PHONE_PLACE = re.compile(
    r"(?<![a-z0-9])(?:on|from|in|of)\s+(?:my|the)\s+(?:phone|mobile)(?![a-z0-9])"
    r"|(?<![a-z0-9])my\s+(?:phone|mobile)(?:'s)?(?!\s*(?:number|no\b|call))(?![a-z0-9])"
    r"|(?<![a-z0-9])(?:phone|mobile)\s+(?:par|pe|per|mein|me|se)(?![a-z0-9])"
    r"|(?<![a-z0-9])(?:phone|mobile)\s+(?:ka|ke|ki)\s+(?!number|no\b|nambar)"
    rf"|(?<![{_DEVANAGARI}])(?:फ़ोन|फोन|मोबाइल)\s+(?:पर|पे|में|से)(?![{_DEVANAGARI}])"
    rf"|(?<![{_DEVANAGARI}])(?:फ़ोन|फोन|मोबाइल)\s+(?:का|के|की)\s+(?!नंबर|नम्बर)",
    re.IGNORECASE,
)


def _says(text: str, word: str) -> bool:
    if re.search(f"[{_DEVANAGARI}]", word):
        return bool(re.search(rf"(?<![{_DEVANAGARI}]){re.escape(word)}(?![{_DEVANAGARI}])", text))
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text))


def _label_words(label: str) -> list[str]:
    """The words of a device's own name that are names: "Studio" of "Studio Mac"."""
    return [
        w for w in re.findall(r"[a-z0-9]+", label.lower()) if len(w) >= 3 and w not in _NOT_A_NAME
    ]


def named_kinds(text: str) -> set[str]:
    """The kinds of device a sentence names."""
    lower = text.lower()
    return {
        kind for kind, words in _KIND_WORDS.items() if any(_says(lower, word) for word in words)
    }


def named_devices(text: str, roster: list[Roster]) -> set[int] | None:
    """The devices a sentence names. None: it names none. Empty: it names a device this person
    does not have (an iPhone, when they have none)."""
    lower = text.lower()
    kinds = named_kinds(text)
    found = {d.id for d in roster if d.kind in kinds}
    # Their own names: "Pixel 7", "Studio".
    found |= {
        d.id
        for d in roster
        if _says(lower, d.label.lower()) or any(_says(lower, w) for w in _label_words(d.label))
    }
    if _PHONE_PLACE.search(text) and not kinds & set(_PHONE_KINDS):
        phones = {d.id for d in roster if d.kind in _PHONE_KINDS}
        return found | phones
    if found:
        return found
    # A computer word fits a Mac or a PC: only someone with neither has named what they lack.
    missing = kinds - {"mac", "windows"} if not (kinds & {"mac", "windows"}) else kinds
    if {"mac", "windows"} & kinds and not any(d.kind in ("mac", "windows") for d in roster):
        return set()
    return set() if missing else None
