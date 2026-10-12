"""Speech-to-text and text-to-speech providers.

STT:
* ``ChatAudioSTT``: an OpenAI-compatible chat model that accepts
  ``input_audio`` parts (for example Voxtral on Amazon Bedrock's Mantle
  endpoint, or an audio-capable OpenAI model).
* ``WhisperSTT``: the ``/audio/transcriptions`` endpoint (OpenAI Whisper and
  compatible servers).

TTS:
* ``PollyTTS``: Amazon Polly through botocore (``pip install "ira-assistant[aws]"``).
* ``OpenAITTS``: the ``/audio/speech`` endpoint.

Fakes for both live here too, for tests and the no-key demo.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, Protocol

from ira.models.base import ProviderError
from ira.models.http import HttpClient


class SpeechToText(Protocol):
    name: str

    async def transcribe(self, wav: bytes) -> str: ...


class TextToSpeech(Protocol):
    name: str

    async def speak(self, text: str) -> bytes:
        """Return MP3 audio."""
        ...


DEFAULT_TRANSCRIBE_PROMPT = (
    "Transcribe this audio exactly as spoken, in the language spoken. "
    "Do not translate, summarise, answer or add anything. "
    "Reply with the transcript only, or nothing if there is no speech."
)


def _clean_transcript(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    for prefix in ("Transcript:", "Transcription:"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix) :].strip()
    return text


class ChatAudioSTT:
    name = "chat_audio"

    def __init__(
        self,
        http: HttpClient,
        model: str,
        *,
        prompt: str | None = None,
        vocabulary: list[str] | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.http = http
        self.model = model
        self.prompt = prompt or DEFAULT_TRANSCRIBE_PROMPT
        if vocabulary:
            # Names a model has never heard are the usual mistakes; listing them helps.
            self.prompt += " Words you may hear: " + ", ".join(vocabulary) + "."
        self.timeout = timeout

    async def transcribe(self, wav: bytes) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.prompt},
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64.b64encode(wav).decode(),
                                "format": "wav",
                            },
                        },
                    ],
                }
            ],
        }
        data = await self.http.post_json("/chat/completions", payload, timeout=self.timeout)
        try:
            content = data["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError):
            raise ProviderError("transcription response had no text", kind="server") from None
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return _clean_transcript(str(content))


class WhisperSTT:
    name = "whisper"

    def __init__(
        self, http: HttpClient, model: str = "whisper-1", *, prompt: str | None = None
    ) -> None:
        self.http = http
        self.model = model
        self.prompt = prompt

    async def transcribe(self, wav: bytes) -> str:
        fields = {"model": self.model, "response_format": "json"}
        if self.prompt:
            fields["prompt"] = self.prompt
        data = await self.http.post_multipart(
            "/audio/transcriptions",
            data=fields,
            files={"file": ("audio.wav", wav, "audio/wav")},
        )
        return _clean_transcript(str(data.get("text", "")))


class OpenAITTS:
    name = "openai"

    def __init__(self, http: HttpClient, model: str = "tts-1", voice: str = "alloy") -> None:
        self.http = http
        self.model = model
        self.voice = voice

    async def speak(self, text: str) -> bytes:
        body = json.dumps(
            {"model": self.model, "voice": self.voice, "input": text, "response_format": "mp3"}
        ).encode()
        return await self.http.post("/audio/speech", body, accept="audio/mpeg")


class PollyTTS:
    name = "polly"

    def __init__(
        self,
        *,
        voice: str = "Joanna",
        engine: str = "neural",
        region: str = "us-east-1",
        language_code: str | None = None,
        client: Any = None,
    ) -> None:
        if client is None:
            try:
                import botocore.session
            except ImportError as exc:  # pragma: no cover - only without the extra
                raise RuntimeError(
                    'Polly needs botocore: pip install "ira-assistant[aws]"'
                ) from exc
            client = botocore.session.get_session().create_client("polly", region_name=region)
        self.client = client
        self.voice = voice
        self.engine = engine
        self.language_code = language_code

    def _synthesize(self, text: str) -> bytes:
        params: dict[str, Any] = {
            "Text": text,
            "OutputFormat": "mp3",
            "VoiceId": self.voice,
            "Engine": self.engine,
        }
        if self.language_code:
            params["LanguageCode"] = self.language_code
        try:
            response = self.client.synthesize_speech(**params)
        except Exception as exc:  # botocore's ClientError, NoCredentialsError, ...
            raise ProviderError(f"polly: {type(exc).__name__}: {exc}", kind="server") from None
        return response["AudioStream"].read()

    async def speak(self, text: str) -> bytes:
        return await asyncio.to_thread(self._synthesize, text)


# A few frames of silent MPEG-1 Layer III audio: valid MP3 that players accept.
_SILENT_FRAME = b"\xff\xfb\x90\x64" + bytes(413)


class FakeSTT:
    name = "fake"

    def __init__(self, text: str = "what are your opening hours") -> None:
        self.text = text
        self.received: list[bytes] = []

    async def transcribe(self, wav: bytes) -> str:
        self.received.append(wav)
        return self.text


class FakeTTS:
    name = "fake"

    def __init__(self, voice: str = "demo") -> None:
        self.voice = voice
        self.spoken: list[str] = []

    async def speak(self, text: str) -> bytes:
        self.spoken.append(text)
        return _SILENT_FRAME * 4
