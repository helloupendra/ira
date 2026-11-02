"""An answer that says something happened, or is about to, when no tool ran.

Models write "Done, I opened Safari", "main dekhti hoon" and "Haan bolo" and end the turn there.
Only the words are looked at here, in English, Hinglish and Hindi, so this finds a turn to check
and proves nothing. What such a turn gets is in ``Assistant._turn``: a round in which the model must
call a tool or say it is finished, in words that are checked again.
"""

from __future__ import annotations

import re

_DONE = re.compile(
    r"(?<![a-z])(?<!n't )(?<!not )(?:done|opened|i opened|i've opened|i have opened|i set|"
    r"i've set|i sent|i've sent|"
    r"i closed|i started|i turned|i clicked|i typed|i read|i called|has been opened|has been set|"
    r"khol diya|khol di|khola hai|kholi hai|bhej diya|bhej di|laga diya|laga di|set kar diya|"
    r"kar diya|kar di|ho gaya|ho gayi|chala diya|chala di|band kar diya|maine kiya|function call)"
    r"(?![a-z])"
    r"|खोल दिया|खोल दी|भेज दिया|भेज दी|लगा दिया|लगा दी|सेट कर दिया|कर दिया|कर दी|हो गया|हो गई|"
    r"चला दिया|चला दी|बंद कर दिया|मैंने किया",
    re.IGNORECASE,
)
# First person, now or next: "dekhti hoon", "khol raha hoon", "karungi", "देखता हूँ", "let me".
_WILL = re.compile(
    r"(?<![a-z])(?:let me(?! know)|i'll(?! be\b)|i will(?! be\b)|i am going to|i'm going to|"
    r"i am now|i'm now|i'm checking|"
    r"i am checking|i'm opening|i'm looking|i'm reading|checking now|one moment|just a moment|"
    r"give me a moment|hold on)(?![a-z])"
    r"|(?<![a-z])[a-z]+(?:ta|ti)\s+(?:hoon|hun|hu)(?![a-z])"
    r"|(?<![a-z])[a-z]+\s+(?:raha|rahi)\s+(?:hoon|hun|hu)(?![a-z])"
    r"|(?<![a-z])[a-z]+(?:unga|ungi|oonga|oongi)(?![a-z])"
    r"|[ऀ-ॿ]+(?:ता|ती)\s+(?:हूं|हूँ)"
    r"|[ऀ-ॿ]+\s+(?:रहा|रही)\s+(?:हूं|हूँ)"
    r"|[ऀ-ॿ]+(?:ूंगा|ूंगी|ूँगा|ूँगी)",
    re.IGNORECASE,
)
# "I can", "I want", "I know", "I think": first person, and no promise.
_NOT_A_PROMISE = re.compile(
    r"^(?:sak|chah|jaan|jan|maan|man|samajh|soch|lag|reh|sak|hot)(?:ta|ti)\b"
    r"|^(?:सक|चाह|जान|मान|समझ|सोच|लग|रह|हो)(?:ता|ती)",
    re.IGNORECASE,
)
_WHICH = re.compile(
    r"which device|which phone|which one of your|on which device|kis device|kis phone|"
    r"kaunse device|kaun se device|kaunsa phone|phone kaunsa|konsa phone"
    r"|किस डिवाइस|कौन से डिवाइस|कौनसे डिवाइस|किस फ़ोन|किस फोन|कौन सा फ़ोन|कौन सा फोन",
    re.IGNORECASE,
)
# Asking for a yes in words: only the app's card can take it.
_YES_IN_WORDS = re.compile(
    r"haan bol|haan kah|han bol|say yes|reply yes|please confirm|kya bhej|bhej dun|bhej doon|"
    r"bhejun\b|shall i (?:send|open|set|call|do)|should i (?:send|open|set|call|do)|"
    r"do you want me to|want me to (?:send|open|set|call)"
    r"|हाँ बोल|हां बोल|हाँ कह|हां कह|कन्फर्म कर|क्या भेज",
    re.IGNORECASE,
)
# Saying it cannot is an answer, whatever else the sentence says.
_CANNOT = re.compile(
    r"can't|cannot|can not|won't|unable|not able|never read|nahi kar (?:sakt|paung|pa)|"
    r"nahi ho sakta|nahin kar sakt|nahi padh sakt|nahi dekh sakt"
    r"|नहीं कर सकत|नहीं कर पा|नहीं हो सकता|नहीं पढ़ सकत|नहीं देख सकत",
    re.IGNORECASE,
)
# Said to her, not asking for anything: nothing here can be an empty promise.
_CHATTER = re.compile(
    r"\s*(?:thank you|thanks|thank you so much|thanks a lot|ok|okay|okay thanks|ok thanks|hi|hello|"
    r"hey|bye|good morning|good night|good evening|namaste|namaskar|shukriya|dhanyavaad|dhanyawad|"
    r"theek hai|thik hai|achha|acha|haan|han|nahi|"
    r"धन्यवाद|शुक्रिया|नमस्ते|नमस्कार|ठीक है|अच्छा|हाँ|हां|नहीं)[\s.!।]*",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"[^.!?।\n]*[.!?।\n]+|[^.!?।\n]+$")
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
    """It says it is doing something, or is about to. A question is not a promise."""
    for sentence in _SENTENCE.findall(text):
        if sentence.rstrip().endswith("?"):
            continue
        for match in _WILL.finditer(sentence):
            if not _NOT_A_PROMISE.match(match.group(0)):
                return True
    return False


def says_cannot(text: str) -> bool:
    return bool(_CANNOT.search(text))


def is_chatter(text: str) -> bool:
    return bool(_CHATTER.fullmatch(text))


def asks_which_device(text: str) -> bool:
    return bool(_WHICH.search(text))


def asks_yes_in_words(text: str) -> bool:
    return bool(_YES_IN_WORDS.search(text))


def asks_more_than_one_thing(text: str) -> bool:
    return bool(_AND_THEN.search(text))


def doubtful(text: str) -> bool:
    return claims_done(text) or promises(text) or asks_which_device(text) or asks_yes_in_words(text)


def without_promises(text: str, claims: bool = False) -> str:
    """The answer with its promises taken out, and with ``claims`` what it says it did too: what
    it found stands, what it never did goes."""
    kept = (
        s for s in _SENTENCE.findall(text) if not promises(s) and not (claims and claims_done(s))
    )
    return "".join(kept).strip()


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
