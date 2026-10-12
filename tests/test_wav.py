from __future__ import annotations

import io
import math
import struct
import wave

import pytest

from ira.voice.audio import AudioError, check_wav, ogg_to_wav, pcm16_wav, to_mono16k, wav_info


def tone(seconds: float = 0.5, rate: int = 16000, channels: int = 1, width: int = 2) -> bytes:
    frames = int(seconds * rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(width)
        writer.setframerate(rate)
        samples = []
        for i in range(frames):
            value = math.sin(2 * math.pi * 440 * i / rate)
            for _ in range(channels):
                if width == 1:
                    samples.append(struct.pack("<B", int(128 + 100 * value)))
                else:
                    samples.append(struct.pack("<h", int(12000 * value)))
        writer.writeframes(b"".join(samples))
    return buffer.getvalue()


def test_valid_wav_is_described():
    info = check_wav(tone(0.5))
    assert (info.sample_rate, info.channels, info.sample_width) == (16000, 1, 2)
    assert info.seconds == pytest.approx(0.5)


@pytest.mark.parametrize("data", [b"", b"hello", b"RIFF" + b"\x00" * 60, b"OggS" + b"\x00" * 60])
def test_non_wav_data_is_refused(data):
    with pytest.raises(AudioError):
        check_wav(data)


def test_empty_and_too_long_recordings_are_refused():
    with pytest.raises(AudioError, match="empty"):
        check_wav(tone(0))
    with pytest.raises(AudioError, match="limit is 1s"):
        check_wav(tone(2), max_seconds=1)


def test_stereo_44k_becomes_mono_16k():
    converted = to_mono16k(tone(1.0, rate=44100, channels=2))
    info = wav_info(converted)
    assert (info.sample_rate, info.channels, info.sample_width) == (16000, 1, 2)
    assert info.frames == pytest.approx(16000, abs=2)


def test_48k_uses_integer_decimation_and_keeps_the_signal():
    converted = to_mono16k(tone(0.25, rate=48000))
    with wave.open(io.BytesIO(converted)) as reader:
        samples = struct.unpack(f"<{reader.getnframes()}h", reader.readframes(reader.getnframes()))
    assert len(samples) == 4000
    assert max(samples) > 8000  # a 440 Hz tone survives averaging by 3


def test_8_bit_wav_is_widened():
    info = wav_info(to_mono16k(tone(0.1, rate=8000, width=1)))
    assert (info.sample_rate, info.sample_width) == (16000, 2)


def test_16k_mono_passes_through_untouched():
    original = tone(0.2)
    assert to_mono16k(original) is original


def test_pcm16_wav_round_trip():
    data = pcm16_wav(b"\x01\x00\x02\x00", 16000)
    with wave.open(io.BytesIO(data)) as reader:
        assert reader.readframes(2) == b"\x01\x00\x02\x00"


def test_ogg_opus_decodes_to_16k_wav():
    soundfile = pytest.importorskip("soundfile")
    import numpy as np

    rate = 48000
    t = np.arange(int(rate * 0.5)) / rate
    pcm = (0.3 * np.sin(2 * np.pi * 440 * t)).astype("float32")
    buffer = io.BytesIO()
    try:
        soundfile.write(buffer, pcm, rate, format="OGG", subtype="OPUS")
    except Exception as exc:  # an old libsndfile without Opus
        pytest.skip(f"this libsndfile cannot write Opus: {exc}")

    info = wav_info(ogg_to_wav(buffer.getvalue()))

    assert (info.sample_rate, info.channels) == (16000, 1)
    assert info.seconds == pytest.approx(0.5, abs=0.1)


def test_garbage_ogg_is_a_clear_error():
    pytest.importorskip("soundfile")
    with pytest.raises(AudioError):
        ogg_to_wav(b"OggS not really")
