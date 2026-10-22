"""Real-time voice: sign-in, a whole turn, barge-in, typed turns, timings, and the splitter."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ira.channels.http import create_app
from ira.models.fake import ScriptedProvider
from ira.voice.live import Sentences, languages_for
from ira.voice.providers import FakeSTT, FakeTTS

from .conftest import make_runtime

pytestmark = pytest.mark.anyio

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret
AUDIO = b"\x01\x00" * 1600  # 100 ms of 16 kHz PCM16


def runtime_with(provider=None, stt=None, tts=None):
    runtime = make_runtime(
        provider=provider or ScriptedProvider(["Theek hai. Kal subah 9 baje yaad dilaungi."]),
        stt=stt if stt is not None else FakeSTT("kal subah 9 baje yaad dilana"),
        tts=tts if tts is not None else FakeTTS(),
    )
    runtime.accounts.create_user("owner@example.com", PASSWORD, "owner")
    runtime.accounts.create_user("viewer@example.com", PASSWORD, "viewer")
    return runtime


def session(client, email="owner@example.com"):
    body = {"email": email, "password": PASSWORD, "use_cookie": False}
    token = client.post("/v1/auth/login", json=body).json()["session_token"]
    return {"Authorization": f"Bearer {token}"}


def app(runtime):
    return TestClient(create_app(runtime, start_channels=False))


def until(ws, kind):
    """Messages until one of this type (audio frames are read with their header)."""
    seen = []
    while True:
        message = ws.receive_json()
        if message["type"] == "audio":
            message["audio"] = ws.receive_bytes()
        seen.append(message)
        if message["type"] == kind:
            return seen


def test_a_spoken_turn_is_heard_answered_and_spoken_sentence_by_sentence():
    runtime = runtime_with()
    client = app(runtime)
    with client, client.websocket_connect("/v1/voice/live", headers=session(client)) as ws:
        ws.send_json({"type": "start", "protocol": 1, "client": "test/1", "conversation_id": "c1"})
        ready = ws.receive_json()
        assert ready["type"] == "ready" and ready["protocol"] == 1
        assert ready["conversation_id"] == "c1" and ready["languages"] == ["hi-IN", "en-IN"]
        ws.send_json({"type": "speech_start", "at": 1000.0})
        ws.send_bytes(AUDIO)
        assert ws.receive_json() == {"type": "partial", "text": "kal", "language": "en-IN"}
        ws.send_bytes(AUDIO)
        ws.send_json({"type": "speech_end", "at": 2000.0})
        seen = until(ws, "done")
        heard = seen[0]
        assert heard == {
            "type": "heard",
            "turn": 1,
            "text": "kal subah 9 baje yaad dilana",
            "language": "en-IN",
        }
        audio = [m for m in seen if m["type"] == "audio"]
        assert [a["text"] for a in audio] == ["Theek hai.", "Kal subah 9 baje yaad dilaungi."]
        assert [a["seq"] for a in audio] == [0, 1] and all(a["audio"] for a in audio)
        assert all(len(a["audio"]) == a["bytes"] for a in audio)
        done = seen[-1]
        assert done["turn"] == 1 and done["message_id"] and not done["interrupted"]
        assert done["text"] == "Theek hai. Kal subah 9 baje yaad dilaungi."
        assert {"stt_ms", "model_first_ms", "tts_first_ms"} <= set(done["timings"])
        ws.send_json({"type": "played", "turn": 1, "at": 3234.0})
        ws.send_json({"type": "bye"})
    assert runtime.stt.received == [AUDIO * 2]
    row = runtime.store.one("SELECT latency_ms, client FROM voice_turns")
    assert (row["latency_ms"], row["client"]) == (1234.0, "test/1")
    # The turn joined the same conversation the web chat uses.
    stored = runtime.store.query(
        "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id", ("http:1:c1",)
    )
    assert [r["role"] for r in stored] == ["user", "assistant"]


def test_speaking_while_ira_talks_stops_its_audio():
    long_answer = " ".join(f"Sentence number {n}." for n in range(40))
    provider = ScriptedProvider([long_answer, "Okay."], delay=0.0)
    runtime = runtime_with(provider=provider)
    client = app(runtime)
    with client, client.websocket_connect("/v1/voice/live", headers=session(client)) as ws:
        ws.send_json({"type": "start", "protocol": 1})
        ws.receive_json()
        ws.send_bytes(AUDIO)  # audio without speech_start starts speech too
        ws.receive_json()  # partial
        ws.send_json({"type": "speech_end", "at": 10.0})
        first = until(ws, "audio")
        assert first[-1]["turn"] == 1
        ws.send_json({"type": "speech_start", "at": 20.0})  # barge-in
        seen = until(ws, "done")
        assert {"type": "interrupted", "turn": 1} in seen
        after = seen[seen.index({"type": "interrupted", "turn": 1}) :]
        assert not [m for m in after if m["type"] == "audio"]
        assert seen[-1]["interrupted"] is True
        ws.send_bytes(AUDIO)
        ws.send_json({"type": "speech_end", "at": 30.0})
        second = until(ws, "done")
        assert second[-1]["turn"] == 2 and second[-1]["text"] == "Okay."


def test_typed_turns_and_a_spoken_length_limit():
    long_answer = " ".join(f"This is sentence {n} of a long answer." for n in range(40))
    runtime = runtime_with(provider=ScriptedProvider([long_answer]))
    client = app(runtime)
    with client, client.websocket_connect("/v1/voice/live", headers=session(client)) as ws:
        ws.send_json({"type": "start", "protocol": 1})
        ws.receive_json()
        ws.send_json({"type": "text", "text": "tell me everything"})
        seen = until(ws, "done")
    spoken = [m["text"] for m in seen if m["type"] == "audio"]
    assert spoken[-1] == "The rest is on your screen."
    assert sum(len(t) for t in spoken[:-1]) <= 640
    assert seen[-1]["text"] == long_answer  # the whole answer is on screen


def test_who_may_call():
    runtime = runtime_with()
    with TestClient(create_app(runtime, start_channels=False)) as client:
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/v1/voice/live") as ws:
            ws.receive_json()
        # A viewer may not talk to Ira.
        with client.websocket_connect(
            "/v1/voice/live", headers=session(client, "viewer@example.com")
        ) as ws:
            assert ws.receive_json() == {
                "type": "error",
                "message": "your role can't talk to Ira by voice",
                "fatal": True,
            }
        # The browser's cookie only from the server's own page.
        cookie = client.post(
            "/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
        ).cookies
        client.cookies = cookie
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(
                "/v1/voice/live", headers={"origin": "https://evil.example"}
            ) as ws,
        ):
            ws.receive_json()
        with client.websocket_connect(
            "/v1/voice/live", headers={"origin": "http://testserver"}
        ) as ws:
            ws.send_json({"type": "start", "protocol": 1})
            assert ws.receive_json()["type"] == "ready"
        client.cookies.clear()
        # A paired Mac speaks for its person, with its device token.
        devices = runtime.hub.devices
        code, _ = devices.start_pairing(1, "mac", "Office Mac", ["files"])
        token, _ = devices.redeem(code)
        with client.websocket_connect(
            "/v1/voice/live", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            ws.send_json({"type": "start", "protocol": 1})
            assert ws.receive_json()["type"] == "ready"


def test_a_server_without_streaming_speech_says_so():
    runtime = runtime_with()
    runtime.stt = None
    client = app(runtime)
    with client, client.websocket_connect("/v1/voice/live", headers=session(client)) as ws:
        error = ws.receive_json()
    assert error["fatal"] is True and "streaming speech-to-text" in error["message"]


def test_sentences_come_out_as_soon_as_they_end():
    cut = Sentences()
    assert cut.feed("Theek hai") == []
    assert cut.feed(". Kal sub") == ["Theek hai."]
    assert cut.feed("ah **9 baje**।") == ["Kal subah 9 baje।"]
    assert cut.feed(" - Upload: 63%\n") == ["Upload: 63%."]
    long = "Your upload is still going and the build tab shows step four of five, " + "x" * 30
    assert cut.feed(long) == [
        "Your upload is still going and the build tab shows step four of five,"
    ]
    assert cut.flush() == ["x" * 30 + "."]
    assert cut.flush() == []


def test_transcribe_languages_follow_what_a_person_speaks():
    assert languages_for(["en", "hi", "hinglish"]) == ["hi-IN", "en-IN"]
    assert languages_for(["hinglish"]) == ["hi-IN"]
    assert languages_for(["en"]) == ["en-IN"]
    assert languages_for([]) == ["en-IN"]


def test_a_long_sentence_with_no_stop_is_cut_at_a_space():
    cut = Sentences()
    words = "aapka upload abhi chal raha hai aur build wala tab bhi chal raha hai " * 3
    first = cut.feed(words)
    assert first and len(first[0]) <= 141 and not first[0].endswith(" ")


def test_a_tool_call_is_announced_and_odd_scripts_are_not_spoken():
    from ira.models.base import ChatResponse, ToolCall

    tool_call = ChatResponse(
        text="", tool_calls=[ToolCall(id="c1", name="nothing_here", arguments="{}")]
    )
    provider = ScriptedProvider([tool_call, "你的上传任务已经完成了。 Upload 63% ho gaya hai."])
    runtime = runtime_with(provider=provider)
    client = app(runtime)
    with client, client.websocket_connect("/v1/voice/live", headers=session(client)) as ws:
        ws.send_json({"type": "start", "protocol": 1})
        ws.receive_json()
        ws.send_json({"type": "text", "text": "upload kitna hua"})
        seen = until(ws, "done")
    spoken = [m["text"] for m in seen if m["type"] == "audio"]
    assert spoken == ["Ek second.", "Upload 63% ho gaya hai."]


async def test_a_call_asks_for_spoken_answers_and_may_use_its_own_tier():
    provider = ScriptedProvider(["Theek hai."])
    runtime = runtime_with(provider=provider)
    runtime.assistant.voice_tier = "default"
    await runtime.assistant.ask("hello", conversation_id="v", channel="voice", user_id=1)
    system = provider.calls[0]["messages"][0].text
    assert "live voice call" in system and "No lists" in system
    assert "Never answer in any other language" in system
    await runtime.assistant.ask("hello", conversation_id="t", channel="web", user_id=1)
    assert "live voice call" not in provider.calls[1]["messages"][0].text


def test_a_proposed_call_is_read_back_with_its_exact_number():
    from typing import Any

    from ira.models.base import ChatResponse, ToolCall
    from ira.tools.personal import PersonalTool

    arguments = '{"name": "Rahul Sharma", "number": "+91 98100 00000"}'
    provider = ScriptedProvider(
        [
            ChatResponse(
                text="", tool_calls=[ToolCall(id="c1", name="call_number", arguments=arguments)]
            ),
            "Rahul ko call karun?",
        ]
    )
    runtime = runtime_with(provider=provider)

    async def never(args: dict[str, Any]) -> Any:
        raise AssertionError("a Tier 2 call waits for a yes")

    runtime.assistant.personal_tools = lambda user_id: [
        PersonalTool(
            name="call_number",
            description="Call a number.",
            parameters={"type": "object", "properties": {}},
            tier=2,
            source="device",
            label="Pixel 7",
            run=never,
            device_id=9,
            skill="calls",
        )
    ]
    client = app(runtime)
    with client, client.websocket_connect("/v1/voice/live", headers=session(client)) as ws:
        ws.send_json({"type": "start", "protocol": 1})
        ws.receive_json()
        ws.send_json({"type": "text", "text": "rahul ko call karo"})
        seen = until(ws, "done")
    spoken = [m["text"] for m in seen if m["type"] == "audio"]
    assert spoken == [
        "Ek second.",
        "call number on Pixel 7: name Rahul Sharma, number +91 98100 00000. Haan ya na?",
    ]
    action = next(m for m in seen if m["type"] == "action")["action"]
    assert action["tier"] == 2 and "+91 98100 00000" in action["summary"]
