"""WAV checks and conversion, and OGG/Opus decoding for Telegram voice notes.

Speech models want short, mono, 16-bit audio; 16 kHz is the usual rate.
Everything here is the standard library except the OGG decoder, which uses
``soundfile`` when installed (``pip install "ira-assistant[ogg]"``) and falls
back to an ``ffmpeg`` binary on PATH.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import wave
from array import array
from dataclasses import dataclass

TARGET_RATE = 16_000


class AudioError(ValueError):
    """Audio that cannot be used, with a message safe to show the user."""


@dataclass(frozen=True)
class WavInfo:
    sample_rate: int
    channels: int
    sample_width: int  # bytes per sample
    frames: int

    @property
    def seconds(self) -> float:
        return self.frames / self.sample_rate if self.sample_rate else 0.0


def wav_info(data: bytes) -> WavInfo:
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise AudioError("not a WAV file")
    try:
        with wave.open(io.BytesIO(data), "rb") as reader:
            return WavInfo(
                sample_rate=reader.getframerate(),
                channels=reader.getnchannels(),
                sample_width=reader.getsampwidth(),
                frames=reader.getnframes(),
            )
    except (wave.Error, EOFError) as exc:
        raise AudioError(f"unreadable WAV ({exc})") from None


def check_wav(data: bytes, *, max_seconds: float = 60.0) -> WavInfo:
    """Validate an uploaded WAV before it costs a speech-to-text call."""
    info = wav_info(data)
    if info.frames == 0:
        raise AudioError("the recording is empty")
    if info.sample_width not in (1, 2, 4):
        raise AudioError(f"{info.sample_width * 8}-bit audio is not supported; send 16-bit PCM")
    if info.channels not in (1, 2):
        raise AudioError("only mono or stereo audio is supported")
    if info.seconds > max_seconds:
        raise AudioError(f"the recording is {info.seconds:.0f}s; the limit is {max_seconds:.0f}s")
    return info


def pcm16_wav(samples: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """Wrap little-endian 16-bit PCM in a WAV header."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(samples)
    return buffer.getvalue()


def _to_int16(raw: bytes, width: int) -> array:
    if width == 2:
        samples = array("h", raw)
    elif width == 1:  # 8-bit WAV is unsigned
        samples = array("h", ((b - 128) << 8 for b in raw))
    elif width == 4:
        wide = array("i", raw)
        if sys.byteorder == "big":
            wide.byteswap()
        return array("h", (s >> 16 for s in wide))
    else:
        raise AudioError(f"{width * 8}-bit audio is not supported")
    if sys.byteorder == "big" and width == 2:
        samples.byteswap()
    return samples


def _resample(samples: array, source: int, target: int) -> array:
    if source == target or not samples:
        return samples
    ratio = source / target
    if source % target == 0:
        # Integer factor (48k -> 16k): average each group, a crude low-pass
        # that is enough for speech recognition.
        step = source // target
        count = len(samples) // step
        return array("h", (sum(samples[i * step : (i + 1) * step]) // step for i in range(count)))
    count = int(len(samples) / ratio)
    last = len(samples) - 1
    out = array("h", bytes(2 * count))
    for j in range(count):
        position = j * ratio
        i = int(position)
        frac = position - i
        nxt = samples[i + 1] if i < last else samples[i]
        out[j] = int(samples[i] + (nxt - samples[i]) * frac)
    return out


def to_mono16k(data: bytes) -> bytes:
    """Any supported PCM WAV -> 16-bit mono 16 kHz WAV."""
    info = check_wav(data, max_seconds=float("inf"))
    if info.sample_rate == TARGET_RATE and info.channels == 1 and info.sample_width == 2:
        return data
    with wave.open(io.BytesIO(data), "rb") as reader:
        raw = reader.readframes(info.frames)
    samples = _to_int16(raw, info.sample_width)
    if info.channels == 2:
        samples = array(
            "h", ((samples[i] + samples[i + 1]) // 2 for i in range(0, len(samples) - 1, 2))
        )
    samples = _resample(samples, info.sample_rate, TARGET_RATE)
    if sys.byteorder == "big":
        samples.byteswap()
    return pcm16_wav(samples.tobytes(), TARGET_RATE, 1)


def ogg_to_wav(data: bytes) -> bytes:
    """Decode OGG/Opus (a Telegram voice note) to 16 kHz mono WAV."""
    try:
        import soundfile
    except ImportError:
        soundfile = None
    if soundfile is not None:
        try:
            pcm, rate = soundfile.read(io.BytesIO(data), dtype="int16", always_2d=True)
        except Exception as exc:  # libsndfile raises its own error type
            raise AudioError(f"could not decode the voice note ({exc})") from None
        channels = pcm.shape[1]
        return to_mono16k(pcm16_wav(pcm.astype("<i2").tobytes(), int(rate), channels))
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
             "-ac", "1", "-ar", str(TARGET_RATE), "-f", "wav", "pipe:1"],
            input=data,
            capture_output=True,
            timeout=60,
        )  # fmt: skip
        if result.returncode != 0 or not result.stdout:
            raise AudioError("ffmpeg could not decode the voice note")
        return _fix_streamed_header(result.stdout)
    raise AudioError(
        'voice notes need an OGG decoder: pip install "ira-assistant[ogg]" or install ffmpeg'
    )


def _fix_streamed_header(data: bytes) -> bytes:
    """ffmpeg writing to a pipe cannot seek back to fill in the sizes; rebuild them."""
    marker = data.find(b"data")
    if marker < 0:
        raise AudioError("ffmpeg returned no audio")
    samples = data[marker + 8 :]
    return pcm16_wav(samples[: len(samples) - len(samples) % 2], TARGET_RATE, 1)
