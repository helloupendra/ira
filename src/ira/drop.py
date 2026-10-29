"""Drop: one person's private inbox, shared by their own devices.

Send text, a link or a file from any of them (the web app, the Mac or Android app,
Telegram, the ``ira`` CLI) and it is on all the others. Items are kept 30 days by
default. Files are stored under the data folder, encrypted at rest with the instance's
secret key, in 1 MB chunks, each bound to its item, its place and whether it is the last,
so none can be swapped, reordered or cut off unnoticed. The server can read them: this is
not end-to-end encryption.

Nothing personal reaches a log: only an item's id, kind and size.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
import secrets
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from ira.store import Store

log = logging.getLogger("ira.drop")

CHUNK = 1024 * 1024
MAGIC = b"IRADROP1"
LINK = re.compile(r"https?://\S+")


class DropError(Exception):
    """A request Drop refuses: ``status`` is the HTTP status that says why."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Item:
    id: int
    user_id: int
    kind: str  # text, link or file
    text: str | None
    name: str | None
    mime: str | None
    size: int | None
    sha256: str | None
    from_device_id: int | None
    from_label: str
    created_at: float
    expires_at: float

    def public(self) -> dict[str, Any]:
        import datetime as dt

        def iso(at: float) -> str:
            return dt.datetime.fromtimestamp(at, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        file = self.kind == "file"  # the file fields are null for text and links
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "name": self.name if file else None,
            "mime": self.mime if file else None,
            "size": self.size if file else None,
            "sha256": self.sha256 if file else None,
            "from_device_id": self.from_device_id,
            "from_label": self.from_label,
            "created_at": iso(self.created_at),
            "expires_at": iso(self.expires_at),
        }


def _item(row: Any) -> Item:
    return Item(
        id=row["id"],
        user_id=row["user_id"],
        kind=row["kind"],
        text=row["text"],
        name=row["name"],
        mime=row["mime"],
        size=row["size"],
        sha256=row["sha256"],
        from_device_id=row["from_device_id"],
        from_label=row["from_label"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


def kind_of(text: str) -> str:
    """A link when the whole trimmed text is one http(s) address, else text."""
    return "link" if LINK.fullmatch(text.strip()) else "text"


def clean_name(name: str | None) -> str:
    """A file name safe to store and to send back: no folders, no control characters."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip(" .")
    return base[:200] or "file"


class Drop:
    def __init__(
        self,
        store: Store,
        folder: Path,
        key: Callable[[], bytes],
        *,
        max_file_bytes: int = 100 * 1024 * 1024,
        max_text: int = 100_000,
        quota_bytes: int = 2 * 1024 * 1024 * 1024,
        keep_seconds: float = 30 * 86400,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.folder = folder
        self._key = key  # read on first use: the key file is not needed until then
        self._aead: Any = None
        self.max_file_bytes = max_file_bytes
        self.max_text = max_text
        self.quota_bytes = quota_bytes
        self.keep_seconds = keep_seconds
        self.clock = clock

    # Encryption.

    def aead(self) -> Any:
        if self._aead is None:
            from ira.connectors.sealed import _aead

            self._aead = _aead(self._key())
        return self._aead

    @staticmethod
    def _aad(user_id: int, item_id: int, index: int, last: bool) -> bytes:
        return f"drop:{user_id}:{item_id}:{index}:{int(last)}".encode()

    def _path(self, user_id: int, item_id: int) -> Path:
        return self.folder / str(user_id) / f"{item_id}.bin"

    # Items.

    def get(self, user_id: int, item_id: int) -> Item | None:
        row = self.store.one(
            "SELECT * FROM drop_items WHERE id = ? AND user_id = ? AND expires_at > ?",
            (item_id, user_id, self.clock()),
        )
        return _item(row) if row else None

    def list(self, user_id: int, *, after_id: int | None = None, limit: int = 50) -> list[Item]:
        """Newest first; ``after_id`` keeps only items newer than it (to catch up)."""
        rows = self.store.query(
            "SELECT * FROM drop_items WHERE user_id = ? AND id > ? AND expires_at > ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, after_id or 0, self.clock(), limit),
        )
        return [_item(r) for r in rows]

    def used_bytes(self, user_id: int) -> int:
        row = self.store.one(
            "SELECT COALESCE(SUM(size), 0) AS n FROM drop_items WHERE user_id = ? "
            "AND expires_at > ?",
            (user_id, self.clock()),
        )
        return int(row["n"]) if row else 0

    def _insert(self, user_id: int, kind: str, text: str | None, **file: Any) -> int:
        now = self.clock()
        cursor = self.store.execute(
            "INSERT INTO drop_items (user_id, kind, text, name, mime, size, sha256, "
            "from_device_id, from_label, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                kind,
                text,
                file.get("name"),
                file.get("mime"),
                file.get("size"),
                file.get("sha256"),
                file.get("from_device_id"),
                file.get("from_label") or "Web",
                now,
                now + self.keep_seconds,
            ),
        )
        return int(cursor.lastrowid or 0)

    def add_text(
        self, user_id: int, text: str, *, from_label: str, from_device_id: int | None = None
    ) -> Item:
        text = text.strip()
        if not text:
            raise DropError("nothing to send")
        if len(text) > self.max_text:
            raise DropError(f"text is limited to {self.max_text:,} characters", 413)
        item_id = self._insert(
            user_id,
            kind_of(text),
            text,
            from_label=from_label,
            from_device_id=from_device_id,
        )
        log.info("drop %s: %s", item_id, kind_of(text))
        item = self.get(user_id, item_id)
        assert item is not None
        return item

    def add_file(
        self,
        user_id: int,
        source: IO[bytes],
        name: str | None,
        mime: str | None,
        *,
        caption: str | None = None,
        from_label: str,
        from_device_id: int | None = None,
    ) -> Item:
        """Store a file read from ``source``, encrypting it chunk by chunk as it comes."""
        name = clean_name(name)
        mime = (mime or "").split(";")[0].strip() or (
            mimetypes.guess_type(name)[0] or "application/octet-stream"
        )
        caption = (caption or "").strip()[: self.max_text] or None
        room = self.quota_bytes - self.used_bytes(user_id)
        limit = min(self.max_file_bytes, room)
        item_id = self._insert(
            user_id,
            "file",
            caption,
            name=name,
            mime=mime,
            size=0,
            from_label=from_label,
            from_device_id=from_device_id,
        )
        path = self._path(user_id, item_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        partial = path.with_suffix(".part")
        digest, size = hashlib.sha256(), 0
        try:
            with partial.open("wb") as out:
                out.write(MAGIC)
                chunk = source.read(CHUNK)
                index = 0
                while True:
                    following = source.read(CHUNK) if chunk else b""
                    last = not following
                    size += len(chunk)
                    if size > limit:
                        too_big = size > self.max_file_bytes
                        raise DropError(
                            f"a file is limited to {self.max_file_bytes // 1024 // 1024} MB"
                            if too_big
                            else "your Drop is full: delete some items first",
                            413 if too_big else 507,
                        )
                    digest.update(chunk)
                    nonce = secrets.token_bytes(12)
                    sealed = self.aead().encrypt(
                        nonce, chunk, self._aad(user_id, item_id, index, last)
                    )
                    out.write(len(sealed).to_bytes(4, "big") + nonce + sealed)
                    if last:
                        break
                    chunk, index = following, index + 1
            partial.chmod(0o600)
            partial.replace(path)
        except BaseException:
            partial.unlink(missing_ok=True)
            self.store.execute("DELETE FROM drop_items WHERE id = ?", (item_id,))
            raise
        self.store.execute(
            "UPDATE drop_items SET size = ?, sha256 = ? WHERE id = ?",
            (size, digest.hexdigest(), item_id),
        )
        log.info("drop %s: file, %d bytes", item_id, size)
        item = self.get(user_id, item_id)
        assert item is not None
        return item

    def read(self, item: Item) -> Iterator[bytes]:
        """A file's bytes, decrypted chunk by chunk; any tampering stops it."""
        path = self._path(item.user_id, item.id)
        with path.open("rb") as stored:
            if stored.read(len(MAGIC)) != MAGIC:
                raise DropError("this file cannot be read", 500)
            index = 0
            while True:
                head = stored.read(4)
                if not head:
                    raise DropError("this file was cut short", 500)
                sealed_length = int.from_bytes(head, "big")
                nonce = stored.read(12)
                sealed = stored.read(sealed_length)
                last = stored.peek(1) == b"" if hasattr(stored, "peek") else False
                try:
                    plain = self.aead().decrypt(
                        nonce, sealed, self._aad(item.user_id, item.id, index, last)
                    )
                except Exception:
                    raise DropError("this file failed its integrity check", 500) from None
                yield plain
                if last:
                    return
                index += 1

    async def stream(self, item: Item) -> AsyncIterator[bytes]:
        import asyncio

        chunks = self.read(item)
        while True:
            chunk = await asyncio.to_thread(next, chunks, None)
            if chunk is None:
                return
            yield chunk

    def delete(self, user_id: int, item_id: int) -> bool:
        cursor = self.store.execute(
            "DELETE FROM drop_items WHERE id = ? AND user_id = ?", (item_id, user_id)
        )
        self._path(user_id, item_id).unlink(missing_ok=True)
        if cursor.rowcount:
            log.info("drop %s: deleted", item_id)
        return cursor.rowcount == 1

    def delete_user(self, user_id: int) -> int:
        rows = self.store.query("SELECT id FROM drop_items WHERE user_id = ?", (user_id,))
        for row in rows:
            self._path(user_id, row["id"]).unlink(missing_ok=True)
        self.store.execute("DELETE FROM drop_items WHERE user_id = ?", (user_id,))
        folder = self.folder / str(user_id)
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
        return len(rows)

    def clean(self) -> int:
        """Delete items past their time, files first. Returns how many."""
        rows = self.store.query(
            "SELECT id, user_id FROM drop_items WHERE expires_at <= ?", (self.clock(),)
        )
        for row in rows:
            self._path(row["user_id"], row["id"]).unlink(missing_ok=True)
            self.store.execute("DELETE FROM drop_items WHERE id = ?", (row["id"],))
        if rows:
            log.info("drop: %d item(s) past their time deleted", len(rows))
        return len(rows)
