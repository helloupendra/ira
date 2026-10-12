"""GET /v1/admin/models: why a model is cooling down, and which voices are valid."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ira.channels.http import create_app
from ira.models.base import ProviderError
from ira.models.fake import ScriptedProvider
from ira.models.gateway import Gateway
from ira.voice.providers import FakeTTS, OpenAITTS, PollyTTS

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
LEAKY = "openai: HTTP 429: quota exceeded for prompt 'refund Riley Demo' key sk-test-not-real"


def models_view(runtime) -> dict:
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    session, _ = runtime.accounts.start_session(owner)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        return client.get("/v1/admin/models", headers={"Authorization": f"Bearer {session}"}).json()


@pytest.mark.anyio
async def test_a_cooling_model_says_why_in_our_own_words():
    from ira.models.base import Message

    busy = ScriptedProvider([ProviderError(LEAKY, kind="capacity", status=429)])
    gateway = Gateway({"a": busy, "b": ScriptedProvider(["fine"])}, {"default": ["a:m", "b:m"]})
    await gateway.chat([Message(role="user", content="hi")])

    reasons = gateway.cooling_reasons()
    assert set(reasons) == set(gateway.cooling()) == {"a:m"}
    assert reasons["a:m"] == {
        "error_kind": "capacity",
        "status": 429,
        "message": "The provider is busy or rate-limited (HTTP 429).",
    }
    assert "Riley" not in str(reasons) and "sk-test" not in str(reasons)

    # A timeout has no status; a success lifts the cool-down and its reason.
    gateway._cool_down("b:m", ProviderError("b:m: no answer", kind="timeout"))
    assert gateway.cooling_reasons()["b:m"]["message"] == "No answer in time."
    busy.script = ["back"]
    await gateway.probe("a:m")
    assert "a:m" not in gateway.cooling_reasons()


def test_the_models_view_carries_the_reasons(registry):
    runtime = make_runtime(registry=registry)
    runtime.gateway._cool_down("fake:m", ProviderError(LEAKY, kind="auth", status=401))
    view = models_view(runtime)
    assert set(view["cooling_reasons"]) == set(view["cooling"]) == {"fake:m"}
    assert view["cooling_reasons"]["fake:m"]["error_kind"] == "auth"
    assert "Riley" not in str(view)


@pytest.mark.parametrize(
    ("tts", "expected"),
    [
        (None, []),
        (FakeTTS(), ["demo"]),
        (OpenAITTS(http=None), ["alloy", "ash", "coral", "echo", "fable", "nova", "onyx"]),
    ],
)
def test_voices_follow_the_text_to_speech_provider(registry, tts, expected):
    voices = models_view(make_runtime(registry=registry, tts=tts))["voices"]
    assert [v["id"] for v in voices][: len(expected)] == expected
    assert len(voices) >= len(expected)


def test_polly_lists_its_neural_voices_for_india_the_us_and_the_uk(registry):
    voices = models_view(make_runtime(registry=registry, tts=PollyTTS(client=object())))["voices"]
    by_id = {v["id"]: v for v in voices}
    assert by_id["Kajal"] == {"id": "Kajal", "languages": ["en-IN", "hi-IN"], "gender": "female"}
    assert by_id["Joanna"]["languages"] == ["en-US"] and by_id["Amy"]["languages"] == ["en-GB"]
    languages = {code for v in voices for code in v["languages"]}
    assert languages == {"en-IN", "hi-IN", "en-US", "en-GB"}
    # Standard-only voices are not offered.
    assert "Aditi" not in by_id and "Raveena" not in by_id
