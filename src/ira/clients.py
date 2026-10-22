"""The clients a person installs: Ira for Mac.

The app is built on a macOS runner in CI (``clients/macos/scripts/make-app.sh``)
and attached to each ``v*`` GitHub Release as ``Ira.dmg``. The server neither
builds nor carries it: ``/v1/downloads`` points at the latest release. The
Python companion and the Chrome extension it served are retired; the app does
both of their jobs.
"""

from __future__ import annotations

from dataclasses import dataclass

RELEASES = "https://github.com/helloupendra/ira/releases/latest"


@dataclass(frozen=True)
class Download:
    name: str
    title: str
    description: str
    url: str


DOWNLOADS = (
    Download(
        "Ira.dmg",
        "Ira for Mac",
        "Open it and drag Ira to Applications. The first time, right-click Ira and choose "
        "Open (on macOS 15 and later: Open Anyway in System Settings, Privacy & Security).",
        f"{RELEASES}/download/Ira.dmg",
    ),
)

# Names of retired downloads, so an old link says where to go instead.
RETIRED = ("ira-mac.zip", "ira-chrome-extension.zip")
