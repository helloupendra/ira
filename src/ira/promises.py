"""An answer that says something happened, or is about to, when no tool ran.

Models write "Done, I opened Safari" and "let me read it" and end the turn there. Only the words
are looked at here, in English, Hinglish and Hindi, so this is a net and not a proof. A turn it
catches gets one more chance to call the tool or say it cannot; see ``Assistant._turn``.
"""

from __future__ import annotations

import re

_DONE = re.compile(
    r"(?<![a-z])(?:done|opened|i opened|i've opened|i have opened|i set|i've set|i sent|i've sent|"
    r"i closed|i started|i turned|i clicked|i typed|i read|i called|has been opened|has been set|"
    r"khol diya|khol di|khola hai|kholi hai|bhej diya|bhej di|laga diya|laga di|set kar diya|"
    r"kar diya|kar di|ho gaya|ho gayi|chala diya|chala di|band kar diya|maine kiya|function call)"
    r"(?![a-z])"
    r"|खोल दिया|खोल दी|भेज दिया|भेज दी|लगा दिया|लगा दी|सेट कर दिया|कर दिया|कर दी|हो गया|हो गई|"
    r"चला दिया|चला दी|बंद कर दिया|मैंने किया",
    re.IGNORECASE,
)
_WILL = re.compile(
    r"(?<![a-z])(?:let me|i'll|i will|i am going to|i'm going to|i'm checking|i am checking|"
    r"checking now|one moment|just a moment|"
    r"main\b[^.!?।\n]{0,60}\b(?:karta|karti|dekhta|dekhti|bhejta|bhejti|kholta|kholti|padhta|padhti|"
    r"lagata|lagati|check karta|check karti)\s+hoon|"
    r"ab main\b|abhi (?:dekhta|dekhti|karta|karti|bhejta|bhejti))(?![a-z])"
    r"|(?:देखता|देखती|करता|करती|भेजता|भेजती|खोलता|खोलती|पढ़ता|पढ़ती|लगाता|लगाती)\s+हूँ"
    r"|(?:देखता|देखती|करता|करती|भेजता|भेजती|खोलता|खोलती|पढ़ता|पढ़ती|लगाता|लगाती)\s+हूं",
    re.IGNORECASE,
)
_WHICH = re.compile(
    r"which device|which one of your|on which device|kis device|kaunse device|kaun se device"
    r"|किस डिवाइस|कौन से डिवाइस|कौनसे डिवाइस",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"[.!?।\n]")
# More than one thing asked in a sentence.
_AND_THEN = re.compile(
    r"(?<![a-z])(?:and|then|aur|phir|fir|uske baad|after that)(?![a-z])|और|फिर|उसके बाद",
    re.IGNORECASE,
)


def claims_done(text: str) -> bool:
    """It says something was done."""
    return bool(_DONE.search(text))


def promises(text: str) -> bool:
    """It says it is doing something, or is about to."""
    return bool(_WILL.search(text))


def asks_which_device(text: str) -> bool:
    return bool(_WHICH.search(text))


def asks_more_than_one_thing(text: str) -> bool:
    return bool(_AND_THEN.search(text))


def doubtful(text: str) -> bool:
    return claims_done(text) or promises(text) or asks_which_device(text)


class PromiseGate:
    """Streamed text, sentence by sentence, held back from the first sentence that may be an empty
    promise: what the model does next decides whether it is ever said. With ``hold_all`` nothing
    goes out until then."""

    def __init__(self, hold_all: bool = False) -> None:
        self._open = ""
        self.held = ""
        self._holding = hold_all

    def feed(self, piece: str) -> str:
        if self._holding:
            self.held += piece
            return ""
        self._open += piece
        out = ""
        while (end := _SENTENCE_END.search(self._open)) is not None:
            sentence, self._open = self._open[: end.end()], self._open[end.end() :]
            if doubtful(sentence):
                self._holding = True
                self.held = sentence + self._open
                self._open = ""
                return out
            out += sentence
        return out

    def flush(self) -> str:
        """The stream ended: a last sentence with no full stop is judged as well."""
        rest, self._open = self._open, ""
        if not rest:
            return ""
        if doubtful(rest):
            self._holding = True
            self.held += rest
            return ""
        return rest

    def take(self) -> str:
        held, self.held = self.held, ""
        return held
