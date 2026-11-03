"""An answer that says something happened, or is about to, when no tool ran.

Models write "Done, I opened Safari", "main dekhti hoon" and "Haan bolo" and end the turn there.
Only the words are looked at here, in English, Hinglish and Hindi, so this finds a turn to check
and proves nothing. What such a turn gets is in ``Assistant._turn``: a round in which the model must
call a tool or say it is finished, in words that are checked again.
"""

from __future__ import annotations

import re

# Her own word that something just happened: "Done.", "I've opened Safari", "Opened it.", "Your
# alarm has been set". Not news or what another did: "The shop opened in 1990", "He sent it".
_DONE = re.compile(
    r"^\s*(?:ok(?:ay)?[\s,!.]+|all\s+)?done(?![a-z])"
    r"|(?<![a-z])(?:it|that|this|everything)(?:'s|\s+is|\s+has\s+been)\s+done(?![a-z])"
    r"|(?<![a-z])i(?:'m|\s+am)\s+done(?![a-z])"
    r"|(?<![a-z])i(?:'ve|\s+have)?\s+(?:just\s+|now\s+)?(?:opened|set|sent|closed|started|turned|"
    r"clicked|typed|called|played|paused|saved|added|deleted|booked)(?![a-z])"
    r"|(?<![a-z])i(?:'ve|\s+have)?\s+(?:just\s+)?read(?![a-z])"
    r"(?!\s+(?:that|about|somewhere|online|in)(?![a-z]))"
    r"|^\s*(?:opened|sent|set|closed|started|turned on|turned off|clicked|typed|called|played|"
    r"saved|added)(?![a-z])"
    r"|(?<![a-z])(?:has|have)\s+been\s+(?:opened|set|sent|started|closed|added|saved)(?![a-z])"
    r"|(?<![a-z])opened\s*[.!]*\s*$"
    r"|(?<![a-z])function call(?![a-z])",
    re.IGNORECASE,
)
# The same in Hinglish and Hindi, unless it is the past it tells of: "cancel ho gaya tha".
_DONE_HI = re.compile(
    r"(?<![a-z])(?:khol diya|khol di|khola hai|kholi hai|bhej diya|bhej di|laga diya|laga di|"
    r"set kar diya|kar diya|kar di|ho gaya|ho gayi|chala diya|chala di|band kar diya|maine kiya)"
    r"(?![a-z])(?!\s+(?:tha|thi|the)(?![a-z]))"
    r"|(?:खोल दिया|खोल दी|भेज दिया|भेज दी|लगा दिया|लगा दी|सेट कर दिया|कर दिया|कर दी|हो गया|हो गई|"
    r"चला दिया|चला दी|बंद कर दिया|मैंने किया)(?!\s*(?:था|थी|थे))",
    re.IGNORECASE,
)
# Someone else did it: "Avery ne bhej diya", "आपने भेज दिया". "maine" and "मैंने" are her own.
_BY_ANOTHER = re.compile(r"(?<![a-z])([a-z]+)\s+ne(?![a-z])|(?<![ऀ-ॿ])([ऀ-ॿ]+)\s+ने(?![ऀ-ॿ])", re.I)
_HER_OWN = {"main", "mai", "mein", "hum", "ham", "मैं", "मै", "हम"}
_SAYS_HERS = re.compile(r"(?<![a-z])maine(?![a-z])|मैंने", re.IGNORECASE)
_THEIRS = re.compile(
    r"(?<![a-z])(?:aapne|apne|tumne|usne|unhone|inhone)(?![a-z])|आपने|तुमने|उसने|उन्होंने", re.I
)
# First person, now or next: "dekhti hoon", "khol raha hoon", "karungi", "देखता हूँ", "let me".
_WILL = re.compile(
    r"(?<![a-z])(?:let me(?! know)|i'll(?! be\b| not\b)|i will(?! be\b| not\b)|i am going to|"
    r"i'm going to|i am now|i'm now|i'm checking|"
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
# Saying it cannot, or that the device is off: an answer, and what led to it in the sentence is too.
_CANNOT = re.compile(
    r"can't|cannot|can not|couldn't|won't|unable|not able|never read|offline|"
    r"(?<![a-z])nahi+n?\s+(?:[a-z]+\s+)?(?:sakt|pa(?:ung|aung)?(?![a-z]))|nahi+n? ho sakta"
    r"|नहीं\s+(?:[ऀ-ॿ]+\s+)?(?:सकत|पा)|नहीं हो सकता|ऑफ़लाइन|ऑफलाइन",
    re.IGNORECASE,
)
# Apps that are never read, on any device: saying so about them is right, not a refusal to correct.
_NEVER_READ = re.compile(
    r"password|passwords|passkey|keychain|bitwarden|lastpass|dashlane|login window|"
    r"पासवर्ड|पास वर्ड|पासकी|कीचेन",
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
    """It says she just did something, sentence by sentence. A question is no claim, nor is a
    past it tells of ("ho gaya tha") or what another did ("The shop opened in 1990", "Avery ne
    bhej diya")."""
    for sentence in _SENTENCE.findall(text):
        if sentence.rstrip().endswith("?"):
            continue
        if _DONE.search(sentence):
            return True
        if _DONE_HI.search(sentence) and not _by_another(sentence):
            return True
    return False


def _by_another(sentence: str) -> bool:
    if _SAYS_HERS.search(sentence):  # "maine apne Mac par khol diya": "apne" is not another's
        return False
    if _THEIRS.search(sentence):
        return True
    return any(
        (m.group(1) or m.group(2)).lower() not in _HER_OWN for m in _BY_ANOTHER.finditer(sentence)
    )


def promises(text: str) -> bool:
    """It says it is doing something, or is about to, sentence by sentence. A question is not a
    promise, nor is what leads to "I can't"; "I can't now, I'll tell you later" still is."""
    for sentence in _SENTENCE.findall(text):
        if sentence.rstrip().endswith("?"):
            continue
        cannot = max((m.end() for m in _CANNOT.finditer(sentence)), default=0)
        for match in _WILL.finditer(sentence):
            if match.start() >= cannot and not _NOT_A_PROMISE.match(match.group(0)):
                return True
    return False


def says_cannot(text: str) -> bool:
    return bool(_CANNOT.search(text))


def names_a_never_read_app(text: str) -> bool:
    return bool(_NEVER_READ.search(text))


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
