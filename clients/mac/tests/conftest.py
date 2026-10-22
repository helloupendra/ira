"""Shared helpers. No test reaches the network: servers here listen on 127.0.0.1 only."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeBrowser:
    """Chrome as the tools see it: answers list_tabs and read_tab from dictionaries."""

    def __init__(self, tabs=None, pages=None):
        self.tabs = tabs or []
        self.pages = pages or {}
        self.requests = []

    async def request(self, op, **fields):
        self.requests.append((op, fields))
        if op == "list_tabs":
            return self.tabs
        if op == "read_tab":
            page = self.pages.get(fields["tabId"])
            if page is None:
                raise RuntimeError(f"No tab with id {fields['tabId']}: it was closed")
            if isinstance(page, list):  # a page that changes: one reading per request
                return page.pop(0) if len(page) > 1 else page[0]
            return page
        raise RuntimeError("unknown request")
