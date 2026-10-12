"""Valid voice ids for each text-to-speech provider type, for the console's voice picker.

Static lists, checked against the providers' documentation:

* ``polly``: Amazon Polly's neural voices for Indian English and Hindi,
  US English and British English (``engine: neural``, the default). Kajal
  speaks both Indian English and Hindi. Polly has more voices and languages;
  any valid id still works in ``ira.yaml``.
* ``openai``: the voices every OpenAI text-to-speech model accepts (tts-1,
  tts-1-hd, gpt-4o-mini-tts). They speak whatever language the text is in.
* ``fake``: the demo voice. ``none``: no voices.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Voice:
    id: str
    languages: tuple[str, ...] = ()  # BCP-47; empty: any language the model speaks
    gender: str | None = None


def _polly(gender: str, languages: tuple[str, ...], *ids: str) -> list[Voice]:
    return [Voice(voice_id, languages, gender) for voice_id in ids]


POLLY_NEURAL: tuple[Voice, ...] = (
    *_polly("female", ("en-IN", "hi-IN"), "Kajal"),
    *_polly(
        "female", ("en-US",), "Danielle", "Ivy", "Joanna", "Kendra", "Kimberly", "Ruth", "Salli"
    ),
    *_polly("male", ("en-US",), "Gregory", "Joey", "Justin", "Kevin", "Matthew", "Stephen"),
    *_polly("female", ("en-GB",), "Amy", "Emma"),
    *_polly("male", ("en-GB",), "Arthur", "Brian"),
)

OPENAI: tuple[Voice, ...] = tuple(
    Voice(voice_id)
    for voice_id in ("alloy", "ash", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer")
)

VOICES: dict[str, tuple[Voice, ...]] = {
    "polly": POLLY_NEURAL,
    "openai": OPENAI,
    "fake": (Voice("demo"),),
    "none": (),
}


def voices_for(provider_type: str | None) -> tuple[Voice, ...]:
    """The valid voices for a ``voice.tts.type``; none for an unknown type or no TTS."""
    return VOICES.get(provider_type or "none", ())
