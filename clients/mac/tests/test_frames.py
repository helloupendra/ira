"""The length-prefixed JSON frames of Chrome native messaging."""

from __future__ import annotations

import asyncio
import io
import struct

import pytest

from ira_mac.frames import (
    MAX_TO_CHROME,
    FrameError,
    encode,
    read_frame,
    read_frame_async,
    write_frame,
)


def test_a_frame_is_a_native_length_then_utf8_json():
    data = encode({"text": "नमस्ते", "n": 1})
    (length,) = struct.unpack("=I", data[:4])
    assert length == len(data) - 4
    assert data[4:].decode() == '{"text":"नमस्ते","n":1}'


def test_round_trip_and_a_clean_end():
    stream = io.BytesIO()
    write_frame(stream, {"id": 1, "op": "list_tabs"})
    write_frame(stream, ["a", 2])
    stream.seek(0)
    assert read_frame(stream) == {"id": 1, "op": "list_tabs"}
    assert read_frame(stream) == ["a", 2]
    assert read_frame(stream) is None


def test_limits_and_broken_frames():
    with pytest.raises(FrameError, match="over the"):
        encode({"text": "x" * MAX_TO_CHROME}, MAX_TO_CHROME)
    with pytest.raises(FrameError, match="over the"):
        read_frame(io.BytesIO(struct.pack("=I", 100) + b"{}"), limit=10)
    with pytest.raises(FrameError, match="ended inside"):
        read_frame(io.BytesIO(struct.pack("=I", 10) + b"{}"))
    with pytest.raises(FrameError, match="ended inside"):
        read_frame(io.BytesIO(b"\x01\x00"))
    with pytest.raises(FrameError, match="JSON"):
        read_frame(io.BytesIO(struct.pack("=I", 3) + b"{x}"))


def test_async_reading():
    async def go():
        reader = asyncio.StreamReader()
        reader.feed_data(encode({"ok": True}) + encode([1]))
        reader.feed_eof()
        return [await read_frame_async(reader) for _ in range(3)]

    assert asyncio.run(go()) == [{"ok": True}, [1], None]
