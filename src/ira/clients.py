"""The clients a person installs, as downloads: the Mac installer and the Chrome extension.

The same zips are served by the IRA server (``/v1/downloads/<name>``) and
attached to GitHub Releases by CI. They are built from ``clients/`` in a
checkout, or from the copy packaged inside the wheel. Nothing in them is
signed yet: no signing key exists in the repository.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

PACKAGED = Path(__file__).resolve().parent / "client_files"  # inside a wheel
CHECKOUT = Path(__file__).resolve().parents[2] / "clients"

EXTENSION_FILES = (
    "manifest.json",
    "background.js",
    "reader.js",
    "popup.html",
    "popup.js",
    "popup.css",
    "README.md",
    "icons/icon-16.png",
    "icons/icon-48.png",
    "icons/icon-128.png",
)
MAC_FILES = (
    "install.sh",
    "uninstall.sh",
    "README.md",
    "pyproject.toml",
    "ira_mac/__init__.py",
    "ira_mac/__main__.py",
    "ira_mac/bridge.py",
    "ira_mac/config.py",
    "ira_mac/daemon.py",
    "ira_mac/frames.py",
    "ira_mac/host.py",
    "ira_mac/keychain.py",
    "ira_mac/logs.py",
    "ira_mac/pair.py",
    "ira_mac/routine.py",
    "ira_mac/tabs.py",
    "ira_mac/tools.py",
    "ira_mac/watch.py",
)
EXECUTABLE = {"install.sh", "uninstall.sh"}


@dataclass(frozen=True)
class Download:
    name: str
    title: str
    description: str


DOWNLOADS = (
    Download(
        "ira-mac.zip",
        "Ira companion for Mac",
        "Unzip it, then in Terminal: cd ~/Downloads/ira-mac && ./install.sh. "
        "Includes the Chrome extension.",
    ),
    Download(
        "ira-chrome-extension.zip",
        "Ira for Chrome",
        "The Chrome extension on its own: unzip it and choose Load unpacked in "
        "chrome://extensions.",
    ),
)


def root() -> Path | None:
    """Where the client sources are: a checkout's clients/, or the wheel's copy."""
    for candidate in (CHECKOUT, PACKAGED):
        if (candidate / "mac" / "install.sh").is_file():
            return candidate
    return None


def _add(archive: zipfile.ZipFile, source: Path, name: str) -> None:
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    mode = 0o755 if Path(name).name in EXECUTABLE else 0o644
    info.external_attr = (0o100000 | mode) << 16  # a regular file with its permissions
    archive.writestr(info, source.read_bytes())


def build(name: str, base: Path | None = None) -> bytes:
    """One download's zip, the same bytes every time for the same sources."""
    base = base or root()
    if base is None:
        raise FileNotFoundError("the client sources are not on this server")
    extension = base / "chrome-extension"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if name == "ira-mac.zip":
            for file in MAC_FILES:
                _add(archive, base / "mac" / file, f"ira-mac/{file}")
            for file in EXTENSION_FILES:
                _add(archive, extension / file, f"ira-mac/chrome-extension/{file}")
        elif name == "ira-chrome-extension.zip":
            for file in EXTENSION_FILES:
                _add(archive, extension / file, f"ira-chrome-extension/{file}")
        else:
            raise KeyError(name)
    return buffer.getvalue()


def main(argv: list[str] | None = None) -> int:
    """Write every download into a folder: ``python -m ira.clients dist/``."""
    import sys

    args = sys.argv[1:] if argv is None else argv
    out = Path(args[0] if args else "dist")
    out.mkdir(parents=True, exist_ok=True)
    for download in DOWNLOADS:
        (out / download.name).write_bytes(build(download.name))
        print(out / download.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
