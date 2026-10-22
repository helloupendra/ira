"""Turn a chat answer into something worth hearing.

Markdown, tables, code and links read badly aloud, and a long answer is
better read on screen. ``speakable`` strips the formatting and, if the text
is still long, cuts it at a sentence and says where the rest is.
"""

from __future__ import annotations

import re

CUT_NOTE = "Full details are in the text above."

_FENCE = re.compile(r"```.*?(```|$)", re.DOTALL)
_TABLE_ROW = re.compile(r"^\s*\|.*\|?\s*$")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"(?:https?://|www\.)\S+")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*")
_QUOTE = re.compile(r"^\s*>\s?")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_RULE = re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")
# Word boundaries keep snake_case names intact.
_EMPHASIS = re.compile(r"(?<!\w)(\*\*|__|\*|_|~~|`)(?=\S)(.+?)(?<=\S)\1(?!\w)")
_SENTENCE_END = re.compile(r"[.!?\u0964\u0965](?=\s|$)")


def strip_markdown(text: str) -> str:
    text = _FENCE.sub(" ", text)
    lines: list[str] = []
    for line in text.splitlines():
        if _TABLE_ROW.match(line) or _RULE.match(line):
            continue
        line = _HEADING.sub("", line)
        line = _QUOTE.sub("", line)
        line = _BULLET.sub("", line)
        line = _IMAGE.sub(r"\1", line)
        line = _LINK.sub(r"\1", line)
        line = _URL.sub("", line)
        for _ in range(3):  # nested emphasis such as ***bold italic***
            line = _EMPHASIS.sub(r"\2", line)
        line = line.replace("`", "").strip()
        if not line:
            continue
        # A list item or heading becomes its own sentence when spoken.
        if not re.search(r"[.!?:;,\u0964\u0965]$", line):
            line += "."
        lines.append(line)
    spoken = " ".join(lines)
    spoken = re.sub(r"\s+([.,!?;:])", r"\1", spoken)
    spoken = re.sub(r"\s{2,}", " ", spoken)
    return spoken.strip()


def speakable(text: str, max_chars: int = 400) -> str:
    """Plain spoken text, at most about ``max_chars`` plus the cut note."""
    spoken = strip_markdown(text)
    if len(spoken) <= max_chars:
        return spoken
    window = spoken[:max_chars]
    ends = [m.end() for m in _SENTENCE_END.finditer(window)]
    if ends and ends[-1] >= max_chars // 4:
        cut = window[: ends[-1]]
    else:
        # No sentence ends early enough: cut at a word instead.
        cut = window.rsplit(" ", 1)[0].rstrip(",;:-") + "."
    return f"{cut.strip()} {CUT_NOTE}"
