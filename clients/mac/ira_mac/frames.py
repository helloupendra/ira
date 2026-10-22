"""Length-prefixed JSON frames: Chrome native messaging's format, also used on the Unix socket.

Each frame is a 32-bit length in native byte order, then that many bytes of
UTF-8 JSON. Chrome sends at most 64 MB to a host and accepts at most 1 MB back.
"""

from __future__ import annotations

import json
import struct
from typing import Any, BinaryIO

HEADER = struct.Struct("=I")
MAX_TO_CHROME = 1024 * 1024
MAX_FRAME = 8 * 1024 * 1024  # what this side reads at most


class FrameError(ValueError):
    pass


def encode(message: Any, limit: int = MAX_FRAME) -> bytes:
    data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > limit:
        raise FrameError(f"frame of {len(data)} bytes is over the {limit} byte limit")
    return HEADER.pack(len(data)) + data


def decode_body(data: bytes) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise FrameError("a frame must be UTF-8 JSON") from None


def check_length(length: int, limit: int = MAX_FRAME) -> None:
    if length > limit:
        raise FrameError(f"frame of {length} bytes is over the {limit} byte limit")


def read_frame(stream: BinaryIO, limit: int = MAX_FRAME) -> Any | None:
    """One frame from a blocking stream; None at a clean end of stream."""
    header = _read_exact(stream, HEADER.size)
    if header is None:
        return None
    (length,) = HEADER.unpack(header)
    check_length(length, limit)
    body = _read_exact(stream, length)
    if body is None:
        raise FrameError("the stream ended inside a frame")
    return decode_body(body)


def write_frame(stream: BinaryIO, message: Any, limit: int = MAX_FRAME) -> None:
    stream.write(encode(message, limit))
    stream.flush()


def _read_exact(stream: BinaryIO, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            if chunks or size == 0:
                raise FrameError("the stream ended inside a frame")
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


async def read_frame_async(reader: Any, limit: int = MAX_FRAME) -> Any | None:
    """One frame from an asyncio StreamReader; None at a clean end of stream."""
    import asyncio

    try:
        header = await reader.readexactly(HEADER.size)
    except asyncio.IncompleteReadError as exc:
        if exc.partial:
            raise FrameError("the stream ended inside a frame") from None
        return None
    (length,) = HEADER.unpack(header)
    check_length(length, limit)
    try:
        body = await reader.readexactly(length)
    except asyncio.IncompleteReadError:
        raise FrameError("the stream ended inside a frame") from None
    return decode_body(body)
