"""The web chat served at ``/``: plain HTML, CSS and JavaScript, installable as a PWA.

No build step. ``static/app.js`` signs in, streams answers, shows action cards
with a PIN box, records 16 kHz WAV through an AudioWorklet, and speaks replies.
"""

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"
ADMIN_DIR = Path(__file__).resolve().parent / "admin"  # the v0.2 console build goes here


def setup_page() -> str:
    """Where a new owner claims the install: the console's setup screen, or the chat's form."""
    return "/admin/setup" if (ADMIN_DIR / "index.html").is_file() else "/"
