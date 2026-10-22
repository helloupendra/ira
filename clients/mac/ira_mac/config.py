"""Where the companion lives and what it remembers (never the token: that is in the Keychain).

Everything is under ``~/Library/Application Support/ira-mac``: macOS lets a
LaunchAgent read there, while ``~/Documents`` needs a permission the companion
never asks for in this version.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

LABEL = "in.ira.mac"
HOST_NAME = "in.ira.mac"


def home() -> Path:
    override = os.environ.get("IRA_MAC_HOME")
    if override:
        return Path(override)
    return Path.home() / "Library" / "Application Support" / "ira-mac"


def config_path() -> Path:
    return home() / "config.json"


def socket_path() -> Path:
    return home() / "run" / "chrome.sock"


def log_path() -> Path:
    return home() / "logs" / "ira-mac.log"


def given_server() -> str | None:
    """The server that served this download (its server.txt), if any."""
    try:
        text = (home() / "server.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text if text.startswith(("https://", "http://")) and " " not in text else None


@dataclass
class Config:
    server: str = ""  # unknown until paired: never a guess
    device_id: int | None = None
    label: str = "My Mac"
    # Salts this Mac's network hashes, so the server can only tell networks apart.
    network_salt: str = ""

    def websocket_url(self) -> str:
        if not self.server:
            raise ValueError("this Mac is not paired yet: run ./install.sh --pair")
        base = self.server.rstrip("/")
        if base.startswith("https://"):
            return "wss://" + base[len("https://") :] + "/v1/devices/ws"
        if base.startswith("http://"):
            return "ws://" + base[len("http://") :] + "/v1/devices/ws"
        raise ValueError("the server address must start with http:// or https://")


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Config()
    return Config(
        server=str(data.get("server") or ""),
        device_id=data.get("device_id"),
        label=str(data.get("label") or Config.label),
        network_salt=str(data.get("network_salt") or ""),
    )


def salt(config: Config, path: Path | None = None) -> str:
    """This Mac's network salt, made and kept on first use."""
    if not config.network_salt:
        config.network_salt = secrets.token_hex(16)
        save(config, path)
    return config.network_salt


def save(config: Config, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
