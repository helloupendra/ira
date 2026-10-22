"""Speech-to-text with Amazon Transcribe streaming, over its WebSocket API.

One recording is one stream: a presigned ``wss://`` URL (SigV4, service
``transcribe``, signed with botocore's default credentials), then the audio
as 16 kHz mono 16-bit PCM in event-stream ``AudioEvent`` frames, then an
empty frame to end it. Each result's last text is kept, and they are joined.

With two or more languages Transcribe identifies them itself; ``many`` lets
it switch language inside one recording, which suits Hinglish. The role needs
``transcribe:StartStreamTranscriptionWebSocket``.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import struct
import time
import wave
import zlib
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from ira.models.base import ProviderError
from ira.voice.audio import to_mono16k

SERVICE = "transcribe"
PATH = "/stream-transcription-websocket"
CHUNK_BYTES = 3200  # 100 ms of 16 kHz 16-bit mono
PACE = 8.0  # audio goes at up to 8 times real time
QUIET_SECONDS = 5.0  # after the last frame, the final results come within this
_STRING = 7  # event-stream header value type


def encode_event(headers: dict[str, str], payload: bytes) -> bytes:
    """One event-stream message: prelude, its CRC, headers, payload, message CRC."""
    raw = b"".join(
        bytes([len(name)])
        + name.encode()
        + bytes([_STRING])
        + struct.pack(">H", len(value.encode()))
        + value.encode()
        for name, value in headers.items()
    )
    total = 12 + len(raw) + len(payload) + 4
    prelude = struct.pack(">II", total, len(raw))
    message = prelude + struct.pack(">I", zlib.crc32(prelude)) + raw + payload
    return message + struct.pack(">I", zlib.crc32(message))


def decode_event(data: bytes) -> tuple[dict[str, str], bytes]:
    """Headers and payload of one event-stream message, checking both CRCs."""
    if len(data) < 16:
        raise ValueError("event-stream message too short")
    total, headers_length = struct.unpack(">II", data[:8])
    if total != len(data) or struct.unpack(">I", data[8:12])[0] != zlib.crc32(data[:8]):
        raise ValueError("bad event-stream prelude")
    if struct.unpack(">I", data[-4:])[0] != zlib.crc32(data[:-4]):
        raise ValueError("bad event-stream checksum")
    headers: dict[str, str] = {}
    at, end = 12, 12 + headers_length
    while at < end:
        name_length = data[at]
        name = data[at + 1 : at + 1 + name_length].decode()
        at += 1 + name_length
        kind = data[at]
        at += 1
        if kind != _STRING:
            raise ValueError(f"unexpected event-stream header type {kind}")
        (length,) = struct.unpack(">H", data[at : at + 2])
        headers[name] = data[at + 2 : at + 2 + length].decode()
        at += 2 + length
    return headers, data[end:-4]


def audio_event(chunk: bytes) -> bytes:
    return encode_event(
        {
            ":content-type": "application/octet-stream",
            ":event-type": "AudioEvent",
            ":message-type": "event",
        },
        chunk,
    )


def pcm_of(wav: bytes) -> bytes:
    """16 kHz mono 16-bit PCM frames of a WAV."""
    with wave.open(io.BytesIO(to_mono16k(wav)), "rb") as reader:
        return reader.readframes(reader.getnframes())


def query(languages: list[str], identify: str, sample_rate: int = 16_000) -> dict[str, str]:
    params = {"media-encoding": "pcm", "sample-rate": str(sample_rate)}
    if len(languages) == 1:
        params["language-code"] = languages[0]
    elif identify == "many":
        params["identify-multiple-languages"] = "true"
        params["language-options"] = ",".join(languages)
    else:
        params["identify-language"] = "true"
        params["language-options"] = ",".join(languages)
        params["preferred-language"] = languages[0]
    return params


def presign(region: str, params: dict[str, str], session: Any = None) -> str:
    """A wss:// URL valid for 5 minutes, signed with the default AWS credentials."""
    import botocore.session
    from botocore.auth import SigV4QueryAuth
    from botocore.awsrequest import AWSRequest

    session = session or botocore.session.get_session()
    credentials = session.get_credentials()
    if credentials is None:
        raise ProviderError(
            "no AWS credentials found (environment, profile or instance role)", kind="auth"
        )
    host = f"transcribestreaming.{region}.amazonaws.com:8443"
    request = AWSRequest(method="GET", url=f"https://{host}{PATH}?{urlencode(params)}")
    SigV4QueryAuth(credentials.get_frozen_credentials(), SERVICE, region, expires=300).add_auth(
        request
    )
    return "wss://" + request.url.removeprefix("https://")


_KINDS = {
    "BadRequestException": "bad_request",
    "LimitExceededException": "capacity",
    "ServiceUnavailableException": "capacity",
    "ConflictException": "capacity",
    "InternalFailureException": "server",
}


class TranscribeSTT:
    name = "transcribe"

    def __init__(
        self,
        region: str,
        languages: list[str],
        *,
        identify: str = "one",
        timeout: float = 60.0,
        connect: Callable[..., Any] | None = None,
        sign: Callable[[str, dict[str, str]], str] | None = None,
        pace: float = PACE,
    ) -> None:
        if not languages:
            raise ValueError("Transcribe needs at least one language")
        self.region = region
        self.languages = languages
        self.identify = identify
        self.timeout = timeout
        self.pace = pace
        self._connect = connect
        self._sign = sign or presign

    def _error(self, message: str, **kwargs: Any) -> ProviderError:
        return ProviderError(f"transcribe: {message}", **kwargs)

    async def transcribe(self, wav: bytes) -> str:
        try:
            return await asyncio.wait_for(self._stream(pcm_of(wav)), self.timeout)
        except TimeoutError:
            raise self._error(f"no answer in {self.timeout:.0f} s", kind="timeout") from None

    async def _stream(self, pcm: bytes) -> str:
        live = LiveTranscription(self)
        delay = CHUNK_BYTES / 32_000 / self.pace if self.pace else 0.0
        for start in range(0, len(pcm), CHUNK_BYTES):
            live.feed(pcm[start : start + CHUNK_BYTES])
            if delay:
                await asyncio.sleep(delay)
        text, _ = await live.finish(timeout=self.timeout)
        return text

    def live(
        self,
        languages: list[str] | None = None,
        on_partial: Callable[[str, str | None], None] | None = None,
    ) -> LiveTranscription:
        """A stream fed while someone speaks: for real-time voice."""
        return LiveTranscription(self, languages, on_partial)

    async def open(self, languages: list[str]) -> Any:
        """A connected WebSocket for one stream."""
        import websockets

        connect = self._connect or websockets.connect
        url = await asyncio.to_thread(self._sign, self.region, query(languages, self.identify))
        try:
            return await connect(url, max_size=2**20, open_timeout=15)
        except websockets.InvalidStatus as exc:
            status = exc.response.status_code
            hint = (
                ": the role needs transcribe:StartStreamTranscriptionWebSocket"
                if status == 403
                else ""
            )
            kind = "auth" if status in (401, 403) else "bad_request"
            raise self._error(f"HTTP {status}{hint}", kind=kind, status=status) from None
        except OSError as exc:
            raise self._error(f"network error ({type(exc).__name__})", kind="network") from None


class LiveTranscription:
    """One utterance as it is spoken: ``feed`` audio, captions as they come, ``finish``.

    The connection opens at once, while the first audio waits in a queue, so
    its setup overlaps with the person speaking. Each result keeps its latest
    text, final or not: with single-language identification Transcribe closes
    the stream without marking the last result final.
    """

    def __init__(
        self,
        stt: TranscribeSTT,
        languages: list[str] | None = None,
        on_partial: Callable[[str, str | None], None] | None = None,
    ) -> None:
        self.stt = stt
        self.languages = languages or stt.languages
        self.on_partial = on_partial
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.latest: dict[str, tuple[str, str | None]] = {}
        self.updated: float | None = None  # monotonic: when the text last changed
        self.error: ProviderError | None = None
        self.task = asyncio.ensure_future(self._run())

    @property
    def text(self) -> str:
        return " ".join(text for text, _ in self.latest.values() if text).strip()

    @property
    def language(self) -> str | None:
        languages = [language for _, language in self.latest.values() if language]
        return languages[-1] if languages else None

    def feed(self, pcm: bytes) -> None:
        if pcm:
            self.queue.put_nowait(pcm)

    async def finish(self, timeout: float = 5.0) -> tuple[str, str | None]:
        """End the audio and wait for the last results: (text, language)."""
        self.queue.put_nowait(None)
        try:
            await asyncio.wait_for(asyncio.shield(self.task), timeout)
        except TimeoutError:
            self.task.cancel()
            if not self.latest:
                raise self.stt._error(f"no answer in {timeout:.0f} s", kind="timeout") from None
        if self.error is not None:
            raise self.error
        return self.text, self.language

    async def cancel(self) -> None:
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self.task

    async def _run(self) -> None:
        try:
            socket = await self.stt.open(self.languages)
        except ProviderError as exc:
            self.error = exc
            return
        try:
            sender = asyncio.create_task(self._send(socket))
            try:
                await self._receive(socket, sender)
            finally:
                sender.cancel()
        except ProviderError as exc:
            self.error = exc
        finally:
            await socket.close()

    async def _send(self, socket: Any) -> None:
        while True:
            chunk = await self.queue.get()
            if chunk is None:
                await socket.send(audio_event(b""))  # the end of the stream
                return
            for start in range(0, len(chunk), CHUNK_BYTES * 4):
                await socket.send(audio_event(chunk[start : start + CHUNK_BYTES * 4]))

    async def _receive(self, socket: Any, sender: asyncio.Task[None]) -> None:
        import websockets

        while True:
            try:
                if sender.done():
                    sender.result()  # a failed send is the error to report
                    message = await asyncio.wait_for(socket.recv(), QUIET_SECONDS)
                else:
                    message = await socket.recv()
            except TimeoutError:
                return  # all audio sent and nothing more came
            except websockets.ConnectionClosedOK:
                return
            except websockets.ConnectionClosed as exc:
                raise self.stt._error(f"stream closed ({exc.code})", kind="network") from None
            if isinstance(message, str):
                continue
            try:
                headers, payload = decode_event(message)
                body = json.loads(payload or b"{}")
            except ValueError as exc:
                raise self.stt._error(f"unreadable reply ({exc})", kind="server") from None
            if headers.get(":message-type") == "exception":
                kind = headers.get(":exception-type") or headers.get(":event-type", "")
                text = str(body.get("Message") or kind)[:200]
                raise self.stt._error(text, kind=_KINDS.get(kind, "server"))
            if headers.get(":event-type") != "TranscriptEvent":
                continue
            changed = False
            for result in body.get("Transcript", {}).get("Results", []):
                alternatives = result.get("Alternatives") or [{}]
                key = str(result.get("ResultId") or len(self.latest))
                text = str(alternatives[0].get("Transcript") or "")
                if self.latest.get(key, ("",))[0] != text:
                    self.updated = time.monotonic()
                self.latest[key] = (text, result.get("LanguageCode"))
                changed = True
            if changed and self.on_partial is not None:
                self.on_partial(self.text, self.language)
