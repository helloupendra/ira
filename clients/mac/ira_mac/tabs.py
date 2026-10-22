"""Which tab someone means: by id, by words from its title or address, or the active one."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit


class TabError(LookupError):
    pass


def clean_url(url: str | None) -> str:
    """An address without its query or fragment: those can hold tokens and personal data."""
    if not url:
        return ""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _words(text: str) -> list[str]:
    return [w for w in text.lower().replace("-", " ").split() if w]


def _rank(tab: dict[str, Any]) -> tuple[int, int, float]:
    """Prefer the active tab of the focused window, then active tabs, then the newest used."""
    return (
        int(bool(tab.get("active")) and bool(tab.get("focused"))),
        int(bool(tab.get("active"))),
        float(tab.get("lastAccessed") or 0),
    )


def match_tab(
    tabs: list[dict[str, Any]], tab_id: int | None = None, match: str | None = None
) -> dict[str, Any]:
    """The tab a request means.

    * ``tab_id``: exactly that tab;
    * ``match``: tabs whose title or address holds every word, else any word;
      among several, the active one wins;
    * neither: the active tab of the focused window.
    """
    if not tabs:
        raise TabError("no Chrome tabs are open")
    if tab_id is not None:
        for tab in tabs:
            if tab.get("id") == tab_id:
                return tab
        raise TabError(f"no open tab has id {tab_id}")
    if match and match.strip():
        words = _words(match)

        def haystack(tab: dict[str, Any]) -> str:
            return f"{tab.get('title', '')} {tab.get('url', '')}".lower()

        found = [t for t in tabs if all(w in haystack(t) for w in words)]
        if not found:
            found = [t for t in tabs if any(w in haystack(t) for w in words)]
        if not found:
            titles = "; ".join(str(t.get("title") or "untitled") for t in tabs[:10])
            raise TabError(f"no tab matches '{match.strip()}'. Open tabs: {titles}")
        return max(found, key=_rank)
    return max(tabs, key=_rank)
