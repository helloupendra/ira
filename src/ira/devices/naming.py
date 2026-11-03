"""Which of the person's devices a sentence names, in any script, as speech-to-text writes it.

A device the person names is the device they mean: other devices' tools are not on offer for that
turn, whatever the model would like. So a word counts only when it is plainly the device:

* a brand or model said outright ("MacBook", "iPhone", "Pixel se sms bhejo");
* a plain word for a kind ("laptop", "computer", "PC", "phone") only as a place: "on my laptop",
  "laptop par", "computer ki screen", never "charge my laptop", "the computer repair shop" or
  "phone number";
* the device's own name: in full when it has two words or more ("Studio Mac"), a single word of it
  only as a place ("studio par"), and never the owner's name in "Upendra's iPhone" (that is a
  person, often one the sentence is about) nor a model word such as "Air" or "Pro".
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


# Brands and models: said anywhere, they name the device.
_KIND_WORDS: dict[str, tuple[str, ...]] = {
    "mac": (
        "mac", "macbook", "mac book", "imac", "mac mini",
        "मैक", "मैकबुक", "मैक बुक", "मेकबुक", "मेक बुक",
    ),
    "windows": (),
    "ios": ("iphone", "i phone", "ipad", "आईफोन", "आई फोन", "आईफ़ोन", "आई फ़ोन", "आईपैड"),
    "android": (
        "android", "pixel", "samsung", "galaxy", "oneplus", "redmi",
        "एंड्रॉयड", "एंड्रॉइड", "पिक्सल", "पिक्सेल", "सैमसंग",
    ),
}  # fmt: skip
# Plain words for a kind: they name it only as a place. "laptop" and "computer" are whichever
# computer they have; "windows" is also what a room has.
_PLACE_WORDS: dict[str, tuple[str, ...]] = {
    "mac": ("laptop", "computer", "लैपटॉप", "कंप्यूटर", "कम्प्यूटर"),
    "windows": ("pc", "windows", "laptop", "computer", "विंडोज", "लैपटॉप", "कंप्यूटर", "कम्प्यूटर"),
}  # fmt: skip
_PHONE_KINDS = ("ios", "android")
_NOT_A_NAME = {
    "my", "the", "phone", "mobile", "ira", "and", "for", "ios", "android", "mac", "ka",
    # Model words: "MacBook Air" is not named by "the air conditioner".
    "pro", "max", "air", "mini", "plus", "ultra", "lite", "note", "fold", "flip", "book",
}  # fmt: skip
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


def _as_place(text: str, word: str) -> bool:
    """The word said as where something is or happens: "on my laptop", "laptop par", "laptop se",
    "laptop ki screen", "my laptop's screen"; not "charge my laptop" or "laptop ka number"."""
    w = re.escape(word)
    if re.search(f"[{_DEVANAGARI}]", word):
        d = _DEVANAGARI
        return bool(
            re.search(rf"(?<![{d}]){w}\s+(?:पर|पे|में|से|का|के|की)(?![{d}])(?!\s*(?:नंबर|नम्बर))", text)
        )
    return bool(
        re.search(
            rf"(?<![a-z0-9])(?:on|from|in|of|to|at|using|via)\s+(?:(?:my|the|this|your)\s+)?{w}(?![a-z0-9])"
            rf"|(?<![a-z0-9]){w}'s(?![a-z0-9])"
            rf"|(?<![a-z0-9]){w}\s+(?:par|pe|per|mein|me|se)(?![a-z0-9])"
            rf"|(?<![a-z0-9]){w}\s+(?:ka|ke|ki)\s+(?!number|no\b|nambar)",
            text,
        )
    )


def _label_words(label: str) -> list[str]:
    """The words of a device's own name that are names: "Studio" of "Studio Mac"; never the
    owner's name in "Upendra's iPhone", nor a model word."""
    lower = label.lower().replace("’", "'")
    owners = set(re.findall(r"([a-z0-9]+)'s(?![a-z0-9])", lower))
    return [
        w
        for w in re.findall(r"[a-z0-9]+", lower)
        if len(w) >= 3 and w not in _NOT_A_NAME and w not in owners
    ]


def _names_label(lower: str, label: str) -> bool:
    """The device's own name: in full when it has two words or more, one word only as a place."""
    full = label.lower().replace("’", "'").strip()
    if len(re.findall(r"[a-z0-9]+", full)) >= 2 and _says(lower, full):
        return True
    return any(_as_place(lower, w) for w in _label_words(label))


def named_kinds(text: str) -> set[str]:
    """The kinds of device a sentence names."""
    lower = text.lower().replace("’", "'")
    return {
        kind
        for kind in _KIND_WORDS
        if any(_says(lower, word) for word in _KIND_WORDS[kind])
        or any(_as_place(lower, word) for word in _PLACE_WORDS.get(kind, ()))
    }


def named_devices(text: str, roster: list[Roster]) -> set[int] | None:
    """The devices a sentence names. None: it names none. Empty: it names a device this person
    does not have (an iPhone, when they have none)."""
    lower = text.lower().replace("’", "'")
    kinds = named_kinds(text)
    found = {d.id for d in roster if d.kind in kinds}
    # Their own names: "Pixel 7", "Studio par".
    found |= {d.id for d in roster if _names_label(lower, d.label)}
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
