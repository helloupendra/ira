"""Telling Ira's own voice from the person's, by its words.

A phone's echo cancelling does not catch everything: her voice from the speaker reaches the
microphone and comes back from the speech-to-text as words. They are hers, often in another
script (she writes "Kal do appointments hain", it hears "कल दो अपॉइंटमेंट्स हैं"), so words
are compared by their consonants, which both scripts share. An echo comes back as runs of her
words in her order; a person's reply reuses her words in its own, and is not one.
"""

from __future__ import annotations

import difflib
import re

_DEVANAGARI = {
    "क": "k", "ख": "k", "ग": "g", "घ": "g", "ङ": "n", "च": "c", "छ": "c", "ज": "j", "झ": "j",
    "ञ": "n", "ट": "t", "ठ": "t", "ड": "d", "ढ": "d", "ण": "n", "त": "t", "थ": "t", "द": "d",
    "ध": "d", "न": "n", "प": "p", "फ": "f", "ब": "b", "भ": "b", "म": "m", "य": "y", "र": "r",
    "ल": "l", "व": "v", "श": "s", "ष": "s", "स": "s", "ह": "h", "ं": "n", "ँ": "n", "ड़": "d",
    "ढ़": "d", "ज़": "j", "फ़": "f", "ऱ": "r",
}  # fmt: skip
# Latin spellings of one sound, longest first, each made the letter Devanagari's gives.
_LATIN = (
    ("chh", "\0"), ("ch", "\0"), ("ce", "se"), ("ci", "si"), ("cy", "sy"), ("c", "k"), ("\0", "c"),
    ("kh", "k"), ("gh", "g"), ("jh", "j"), ("th", "t"), ("dh", "d"), ("ph", "f"), ("bh", "b"),
    ("sh", "s"), ("w", "v"), ("z", "j"), ("q", "k"), ("x", "ks"),
)  # fmt: skip
_WORD = re.compile(r"[\w\u0900-\u097f]+")  # with Devanagari's vowel signs, which \\w leaves out
# How much of what was heard must be hers.
ECHO_SHARE = 0.75
# Fewer words than this are the person's at the end of a turn: a "haan" is an answer, even to
# her "haan".
ECHO_WORDS = 3
# Her words in a row that count as her saying them: one word alone proves nothing.
ECHO_RUN = 2


def skeleton(word: str) -> str:
    """A word's consonants, the same in Latin and in Devanagari letters: "hain" and "हैं"."""
    lower = word.lower()
    letters = "".join(_DEVANAGARI.get(char, "") for char in lower)
    latin = "".join(char for char in lower if "a" <= char <= "z" or char.isdigit())
    for spelling, sound in _LATIN:
        latin = latin.replace(spelling, sound)
    consonants = re.sub(r"[aeiou]", "", latin + letters)
    return re.sub(r"(.)\1+", r"\1", consonants)  # "appointments" has one p to the ear


def _share(heard: str, spoken: list[str]) -> tuple[float, int]:
    """How much of what was heard she said lately, in runs in her order, and how many words
    that is of."""
    hers = [s for line in spoken for s in map(skeleton, _WORD.findall(line)) if s]
    words = [s for s in map(skeleton, _WORD.findall(heard)) if s]
    if not words or not hers:
        return 0.0, len(words)
    blocks = difflib.SequenceMatcher(None, words, hers, autojunk=False).get_matching_blocks()
    run = min(ECHO_RUN, len(words))
    return sum(b.size for b in blocks if b.size >= run) / len(words), len(words)


def maybe_echo(heard: str, spoken: list[str]) -> bool:
    """While the person may still be speaking: these words may be hers, so wait for more."""
    share, _ = _share(heard, spoken)
    return share >= ECHO_SHARE


def looks_like_echo(heard: str, spoken: list[str]) -> bool:
    """A whole utterance: she said this, not the person."""
    share, words = _share(heard, spoken)
    return words >= ECHO_WORDS and share >= ECHO_SHARE
