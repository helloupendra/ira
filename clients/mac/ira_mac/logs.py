"""Logs that are safe to keep: tool names, tab ids and timings.

Nothing here ever logs page text. As a second line of defence, every record is
passed through ``redact``: URLs lose their query and fragment, and device
tokens are masked.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

_URL_TAIL = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s?#\"'<>]*)[?#][^\s\"'<>]*", re.IGNORECASE)
_TOKEN = re.compile(r"\birad_[A-Za-z0-9_-]+")
_CODE_FIELD = re.compile(r"(code=)[A-Za-z0-9-]+", re.IGNORECASE)
MAX_LINE = 500


def redact(text: str) -> str:
    text = _URL_TAIL.sub(r"\1", text)
    text = _TOKEN.sub("irad_***", text)
    text = _CODE_FIELD.sub(r"\1***", text)
    return text if len(text) <= MAX_LINE else text[:MAX_LINE] + "..."


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup(path: Path | None = None, level: int = logging.INFO) -> None:
    handler: logging.Handler
    if path is None:
        handler = logging.StreamHandler(sys.stderr)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # The WebSocket library logs frames at debug level; keep it quiet.
    logging.getLogger("websockets").setLevel(logging.WARNING)
