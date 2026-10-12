"""Speech in and out: providers, WAV/OGG handling, and the spoken-text shortener."""

from ira.voice.audio import AudioError, check_wav, ogg_to_wav, to_mono16k
from ira.voice.providers import (
    ChatAudioSTT,
    FakeSTT,
    FakeTTS,
    OpenAITTS,
    PollyTTS,
    SpeechToText,
    TextToSpeech,
    WhisperSTT,
)
from ira.voice.shorten import speakable, strip_markdown

__all__ = [
    "AudioError",
    "ChatAudioSTT",
    "FakeSTT",
    "FakeTTS",
    "OpenAITTS",
    "PollyTTS",
    "SpeechToText",
    "TextToSpeech",
    "WhisperSTT",
    "check_wav",
    "ogg_to_wav",
    "speakable",
    "strip_markdown",
    "to_mono16k",
]
