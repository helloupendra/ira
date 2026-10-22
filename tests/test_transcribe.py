"""Amazon Transcribe streaming: framing, the presigned URL, and a stream against a stand-in."""

from __future__ import annotations

import asyncio
import base64
import json
import struct
import zlib
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from websockets.asyncio.server import serve

from ira.models.base import ProviderError
from ira.voice import transcribe
from ira.voice.audio import pcm16_wav
from ira.voice.transcribe import (
    TranscribeSTT,
    audio_event,
    decode_event,
    encode_event,
    presign,
    query,
)

pytestmark = pytest.mark.anyio

# A TranscriptEvent frame from AWS's WebSocket guide, as printed there.
AWS_SAMPLE = (
    "AAAAUwAAAEP1RHpYBTpkYXRlCAAAAWiXUkMLEDpjaHVuay1z"  # pragma: allowlist secret
    "aWduYXR1cmUGACCt6Zy+uymwEK2SrLp/zVBI5eGn83jdBwCa"  # pragma: allowlist secret
    "RUBJA+eaDafqjqI="  # pragma: allowlist secret
)


def test_checksums_match_awss_own_frame():
    frame = base64.b64decode(AWS_SAMPLE)
    total, _ = struct.unpack(">II", frame[:8])
    assert total == len(frame)
    assert struct.unpack(">I", frame[8:12])[0] == zlib.crc32(frame[:8])
    assert struct.unpack(">I", frame[-4:])[0] == zlib.crc32(frame[:-4])


def test_frames_round_trip_and_damage_is_caught():
    frame = audio_event(b"\x01\x02" * 10)
    headers, payload = decode_event(frame)
    assert headers == {
        ":content-type": "application/octet-stream",
        ":event-type": "AudioEvent",
        ":message-type": "event",
    }
    assert payload == b"\x01\x02" * 10
    assert decode_event(audio_event(b""))[1] == b""
    damaged = frame[:-6] + b"\x00" + frame[-5:]
    with pytest.raises(ValueError, match="checksum"):
        decode_event(damaged)


def test_the_query_names_the_languages():
    assert query(["hi-IN"], "many") == {
        "media-encoding": "pcm",
        "sample-rate": "16000",
        "language-code": "hi-IN",
    }
    many = query(["hi-IN", "en-IN"], "many")
    assert many["identify-multiple-languages"] == "true"
    assert many["language-options"] == "hi-IN,en-IN"
    one = query(["hi-IN", "en-IN"], "one")
    assert (one["identify-language"], one["preferred-language"]) == ("true", "hi-IN")


def test_the_url_is_presigned_for_transcribe():
    botocore = pytest.importorskip("botocore.session")
    session = botocore.get_session()
    session.set_credentials("AKIDEXAMPLE", "secret-for-tests", "token-for-tests")
    url = presign("ap-south-1", query(["hi-IN", "en-IN"], "many"), session)
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc, parts.path) == (
        "wss",
        "transcribestreaming.ap-south-1.amazonaws.com:8443",
        "/stream-transcription-websocket",
    )
    params = parse_qs(parts.query)
    assert params["X-Amz-Credential"][0].endswith("/ap-south-1/transcribe/aws4_request")
    assert params["X-Amz-Expires"] == ["300"]
    assert params["X-Amz-SignedHeaders"] == ["host"]
    assert params["X-Amz-Security-Token"] == ["token-for-tests"]
    assert params["language-options"] == ["hi-IN,en-IN"]
    assert len(params["X-Amz-Signature"][0]) == 64
    assert "secret-for-tests" not in url


def transcript(text: str, partial: bool, language: str = "hi-IN") -> bytes:
    body = {
        "Transcript": {
            "Results": [
                {
                    "Alternatives": [{"Transcript": text}],
                    "IsPartial": partial,
                    "LanguageCode": language,
                }
            ]
        }
    }
    headers = {
        ":content-type": "application/json",
        ":event-type": "TranscriptEvent",
        ":message-type": "event",
    }
    return encode_event(headers, json.dumps(body).encode())


class StandIn:
    """A Transcribe stand-in: counts the audio, then answers as told."""

    def __init__(self, replies: list[bytes], *, close: bool = True, status: int = 0) -> None:
        self.replies = replies
        self.close = close
        self.status = status
        self.audio = 0
        self.frames = 0
        self.params: dict[str, list[str]] = {}

    def refuse(self, connection, request):
        self.params = parse_qs(urlsplit(request.path).query)
        if self.status:
            return connection.respond(self.status, "Forbidden\n")
        return None

    async def handler(self, socket) -> None:
        async for message in socket:
            headers, payload = decode_event(message)
            assert headers[":event-type"] == "AudioEvent"
            self.frames += 1
            if payload:
                self.audio += len(payload)
                continue
            for reply in self.replies:
                await socket.send(reply)
            if self.close:
                return
            await asyncio.sleep(30)


async def run_against(stand_in: StandIn, wav: bytes, **kwargs) -> str:
    async with serve(stand_in.handler, "127.0.0.1", 0, process_request=stand_in.refuse) as server:
        port = server.sockets[0].getsockname()[1]

        def sign(region, params):
            return f"ws://127.0.0.1:{port}/stream-transcription-websocket?{urlencode(params)}"

        stt = TranscribeSTT("ap-south-1", ["hi-IN", "en-IN"], sign=sign, pace=0, **kwargs)
        return await stt.transcribe(wav)


ONE_SECOND = pcm16_wav(b"\x00\x00" * 16_000, 16_000)


async def test_a_recording_is_streamed_and_the_final_results_joined():
    stand_in = StandIn(
        [
            transcript("कल सुबह", True),
            transcript("कल सुबह नौ बजे", False),
            transcript("meeting", True, "en-IN"),
            transcript("meeting hai", False, "en-IN"),
        ]
    )
    heard = await run_against(stand_in, ONE_SECOND)
    assert heard == "कल सुबह नौ बजे meeting hai"
    assert stand_in.audio == 32_000 and stand_in.frames == 11  # ten 100 ms frames, then the end
    assert stand_in.params["identify-multiple-languages"] == ["true"]


async def test_stereo_44k_is_sent_as_16k_mono():
    stereo = pcm16_wav(b"\x00\x00\x00\x00" * 44_100, 44_100, channels=2)
    stand_in = StandIn([transcript("theek hai", False, "en-IN")])
    assert await run_against(stand_in, stereo) == "theek hai"
    assert stand_in.audio == 32_000


async def test_an_exception_from_transcribe_is_a_clear_error():
    headers = {
        ":content-type": "application/json",
        ":exception-type": "BadRequestException",
        ":message-type": "exception",
    }
    refusal = encode_event(headers, json.dumps({"Message": "Unsupported language"}).encode())
    with pytest.raises(ProviderError, match="Unsupported language") as caught:
        await run_against(StandIn([refusal]), ONE_SECOND)
    assert caught.value.kind == "bad_request"


async def test_a_refused_role_names_the_permission():
    with pytest.raises(ProviderError, match="StartStreamTranscriptionWebSocket") as caught:
        await run_against(StandIn([], status=403), ONE_SECOND)
    assert caught.value.kind == "auth"


async def test_a_server_that_stays_open_still_gives_its_results(monkeypatch):
    monkeypatch.setattr(transcribe, "QUIET_SECONDS", 0.2)
    stand_in = StandIn([transcript("aaj ki khabar", False, "en-IN")], close=False)
    assert await run_against(stand_in, ONE_SECOND) == "aaj ki khabar"
