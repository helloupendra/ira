"""Secrets at rest: a connection's token, sealed with AES-GCM.

The key is ``IRA_SECRET_KEY`` (32 bytes, URL-safe base64), or else a key file
made on first use next to the database (``secret.key``, readable only by its
owner). Keep the key out of database backups: with the environment variable,
a copy of the database alone opens nothing. Each secret is bound to its
connection, so one cannot be moved to another row.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from pathlib import Path
from typing import Any

ENV = "IRA_SECRET_KEY"
KEY_FILE = "secret.key"


class SealError(Exception):
    pass


def _aead(key: bytes) -> Any:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - only without the extra
        raise SealError('connections need: pip install "ira-assistant[connectors]"') from exc
    return AESGCM(key)


def load_key(data_dir: Path) -> bytes:
    raw = os.environ.get(ENV)
    if raw:
        try:
            key = base64.urlsafe_b64decode(raw.strip() + "=" * (-len(raw.strip()) % 4))
        except ValueError:
            key = b""
        if len(key) != 32:
            raise SealError(f"{ENV} must be 32 bytes in URL-safe base64")
        return key
    path = data_dir / KEY_FILE
    if path.is_file():
        key = path.read_bytes()
        if len(key) != 32:
            raise SealError(f"{path} is not a 32-byte key")
        return key
    data_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(key)
    return key


class Sealer:
    def __init__(self, key: bytes) -> None:
        self._aead = _aead(key)

    def seal(self, value: dict[str, Any], context: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._aead.encrypt(nonce, json.dumps(value).encode(), context.encode())

    def open(self, blob: bytes, context: str) -> dict[str, Any]:
        try:
            plain = self._aead.decrypt(blob[:12], blob[12:], context.encode())
        except Exception:
            raise SealError("a stored secret could not be opened: was the key changed?") from None
        value = json.loads(plain)
        return value if isinstance(value, dict) else {}
