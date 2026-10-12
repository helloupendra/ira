"""A short label for a User-Agent header, so people can tell their sessions apart.

``device_label`` turns a browser's User-Agent into "Chrome on macOS" or
"Safari on iPhone". It only looks for well-known tokens: no dependency, no
version numbers, and no guessing beyond the browser and the system.
"""

from __future__ import annotations

import re

# Checked in order: many browsers carry another's token too (Edge says Chrome
# and Safari, Chrome says Safari, an iPhone says "like Mac OS X").
_BROWSERS = (
    ("Edge", ("Edg/", "EdgA/", "EdgiOS/", "Edge/")),
    ("Opera", ("OPR/", "Opera")),
    ("Samsung Internet", ("SamsungBrowser/",)),
    ("Firefox", ("Firefox/", "FxiOS/")),
    ("Chrome", ("CriOS/", "Chrome/")),
    ("Chromium", ("Chromium/",)),
    ("Safari", ("Safari/",)),
)

_SYSTEMS = (
    ("iPhone", ("iPhone",)),
    ("iPad", ("iPad",)),
    ("Android", ("Android",)),
    ("Windows", ("Windows",)),
    ("ChromeOS", ("CrOS",)),
    ("macOS", ("Macintosh", "Mac OS X")),
    ("Linux", ("Linux",)),
)

# Clients that are not browsers, by their first product token.
_TOOLS = {
    "curl": "curl",
    "wget": "Wget",
    "python-httpx": "Python (httpx)",
    "python-requests": "Python (requests)",
    "python-urllib": "Python (urllib)",
}

_PRODUCT = re.compile(r"^([A-Za-z][A-Za-z0-9._-]{0,39})")


def _first(user_agent: str, table: tuple[tuple[str, tuple[str, ...]], ...]) -> str | None:
    for label, tokens in table:
        if any(token in user_agent for token in tokens):
            return label
    return None


def device_label(user_agent: str | None) -> str | None:
    """ "Chrome on macOS", "Safari on iPhone", "curl"; None when there is nothing to go on."""
    user_agent = (user_agent or "").strip()
    if not user_agent:
        return None
    product = _PRODUCT.match(user_agent)
    name = product.group(1) if product else ""
    if name.lower() in _TOOLS:
        return _TOOLS[name.lower()]
    browser = _first(user_agent, _BROWSERS)
    system = _first(user_agent, _SYSTEMS)
    if browser and system:
        return f"{browser} on {system}"
    if browser or system:
        return browser or f"A browser on {system}"
    # Something else that names itself, such as "MyKiosk/2.1".
    return name if name and name != "Mozilla" else None
