"""Telling Hindi (Devanagari), Hinglish (Hindi in Latin letters) and English apart.

Used to score replies in ``ira eval language`` and to learn which language a
person likes their answers in. A plain count of words in each script and of
common Hindi words: no model, so the result can be checked by hand.

Quoted data is left out first: addresses, "quoted" and **bold** titles. A
Hindi answer that lists English tab titles is still a Hindi answer.
"""

from __future__ import annotations

import re

LANGUAGES = ("hi", "hinglish", "en")

# Words that mark Hindi written in Latin letters. English words that are also
# Hindi ("tab", "to", "is", "main", "the") are left out on purpose.
HINDI_WORDS = frozenset(
    re.findall(
        r"[a-z]+",
        "hai hain tha thi ho hoga hogi raha rahi rahe kya kyun kaise kaun kaunse konse mein "
        "mujhe mera meri mere aap aapka aapki aapke tum tumhara hamara yeh ye woh wo nahi "
        "nahin haan ji abhi kal aaj subah shaam raat baje ka ki ke ko se pe aur bhi toh sirf "
        "kuch bahut thoda zyada jab tak kar karo karna kiya diya liya gaya gayi hua hui hue "
        "wala wali wale batao bata batana dekho dekh chalo khatam poora khabar khule khula "
        "kitna kitni dhundo theek thik shukriya acha accha bilkul hoon hun yahan wahan agar "
        "chahiye chahte batayein bataiye dijiye lagbhag baki baaki",
    )
)
DEVANAGARI_WORD = re.compile(r"[ऀ-ॿ]+")
LATIN_WORD = re.compile(r"[A-Za-z]+(?:'[a-z]+)?")
# Data, not prose: web addresses and domains, "quoted" and **bold** spans.
DATA = re.compile(r"https?://\S+|\b[\w-]+(?:\.[\w-]+)+(?:/\S*)?|\*\*[^*]+\*\*|\"[^\"]*\"|“[^”]*”")


def prose(text: str) -> str:
    """The text without quoted data, unless nothing else would be left."""
    stripped = DATA.sub(" ", text)
    if LATIN_WORD.search(stripped) or DEVANAGARI_WORD.search(stripped):
        return stripped
    return text


def detect(text: str) -> str:
    """hi (mostly Devanagari words), hinglish (Latin with Hindi words), or en."""
    text = prose(text)
    devanagari = len(DEVANAGARI_WORD.findall(text))
    words = [w.lower() for w in LATIN_WORD.findall(text)]
    if devanagari and devanagari >= len(words):
        return "hi"
    hindi = sum(1 for w in words if w in HINDI_WORDS)
    if hindi >= 2 or (words and hindi / len(words) >= 0.15):
        return "hinglish"
    return "en"
