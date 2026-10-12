"""Wire-format tests for the HTTP providers, against recorded-style responses."""

from __future__ import annotations

import json

import httpx
import pytest

from ira.models.anthropic import AnthropicProvider, to_anthropic
from ira.models.base import Message, StreamDone, TextDelta, ToolCall
from ira.models.http import HeaderKeyAuth, HttpClient
from ira.models.openai_compat import OpenAICompatProvider

pytestmark = pytest.mark.anyio

TOOLS = [{"name": "find_slots", "description": "Free slots", "parameters": {"type": "object"}}]


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def sse(*events: object) -> bytes:
    return "".join(
        f"data: {json.dumps(e) if not isinstance(e, str) else e}\n\n" for e in events
    ).encode()


async def test_openai_compatible_chat_with_tool_calls():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "find_slots",
                                        "arguments": '{"date": "x"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    provider = OpenAICompatProvider(
        HttpClient("https://llm.example.com/v1", client=client(handler))
    )
    response = await provider.chat(
        "m", [Message(role="user", content="hi")], TOOLS, max_tokens=50, timeout=5
    )

    assert seen["url"] == "https://llm.example.com/v1/chat/completions"
    assert seen["body"]["tools"][0]["function"]["name"] == "find_slots"
    assert seen["body"]["max_tokens"] == 50
    assert response.tool_calls == [ToolCall("call_1", "find_slots", '{"date": "x"}')]
    assert (response.usage.input_tokens, response.usage.output_tokens) == (12, 3)


async def test_openai_compatible_stream_assembles_tool_call_deltas():
    body = sse(
        {"choices": [{"delta": {"content": "Let me "}}]},
        {"choices": [{"delta": {"content": "check."}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "c9",
                                "function": {"name": "find_slots", "arguments": '{"da'},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'te": "x"}'}}]}}
            ]
        },
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 9}},
        "[DONE]",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    provider = OpenAICompatProvider(
        HttpClient("https://llm.example.com/v1", client=client(handler))
    )
    events = [
        e
        async for e in provider.stream(
            "m", [Message(role="user", content="hi")], TOOLS, max_tokens=50, timeout=5
        )
    ]

    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Let me ", "check."]
    done = events[-1]
    assert isinstance(done, StreamDone)
    assert done.response.tool_calls == [ToolCall("c9", "find_slots", '{"date": "x"}')]
    assert done.response.usage.output_tokens == 9


def test_anthropic_conversion_merges_tool_results_and_cleans_bad_arguments():
    messages = [
        Message(role="system", content="be brief"),
        Message(role="user", content="hi"),
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall("t1", "a", '{"x": 1}'), ToolCall("t2", "b", "not json")],
        ),
        Message(role="tool", content="r1", tool_call_id="t1"),
        Message(role="tool", content="r2", tool_call_id="t2"),
    ]
    system, turns = to_anthropic(messages)

    assert system == "be brief"
    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert turns[1]["content"][1]["input"] == {}  # invalid arguments replayed as {}
    assert [b["tool_use_id"] for b in turns[2]["content"]] == ["t1", "t2"]


async def test_anthropic_stream_text_and_tool_use():
    body = sse(
        {"type": "message_start", "message": {"usage": {"input_tokens": 20}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Checking"},
        },
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "tu_1", "name": "find_slots"},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"date": '},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '"x"}'},
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 15},
        },
        {"type": "message_stop"},
    )
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        return httpx.Response(200, content=body)

    http = HttpClient(
        "https://api.example.com", HeaderKeyAuth("test-key-123"), client=client(handler)
    )
    provider = AnthropicProvider(http)
    events = [
        e
        async for e in provider.stream(
            "m", [Message(role="user", content="hi")], TOOLS, max_tokens=50, timeout=5
        )
    ]

    assert seen["headers"]["x-api-key"] == "test-key-123"
    assert seen["headers"]["anthropic-version"]
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Checking"]
    response = events[-1].response
    assert response.tool_calls == [ToolCall("tu_1", "find_slots", '{"date": "x"}')]
    assert (response.usage.input_tokens, response.usage.output_tokens) == (20, 15)
    assert response.stop_reason == "tool_use"


async def test_anthropic_overloaded_stream_error_is_a_capacity_error():
    from ira.models.base import ProviderError

    body = sse({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
    http = HttpClient(
        "https://api.example.com",
        client=client(lambda request: httpx.Response(200, content=body)),
    )
    with pytest.raises(ProviderError) as caught:
        async for _ in AnthropicProvider(http).stream(
            "m", [Message(role="user", content="hi")], None, max_tokens=5, timeout=5
        ):
            pass
    assert caught.value.kind == "capacity"


def test_sigv4_signs_for_bedrock_mantle():
    botocore = pytest.importorskip("botocore")
    from botocore.credentials import Credentials

    from ira.models.aws import SigV4Auth, mantle_base_url

    class Session:
        def get_credentials(self):
            return Credentials("test-access-key", "test-secret-key")

    assert botocore
    auth = SigV4Auth("us-east-1", session=Session())
    url = mantle_base_url("us-east-1") + "/chat/completions"
    headers = auth.headers("POST", url, b'{"model": "m"}', "application/json")

    assert url == "https://bedrock-mantle.us-east-1.api.aws/v1/chat/completions"
    assert "/us-east-1/bedrock-mantle/aws4_request" in headers["Authorization"]
    assert "X-Amz-Date" in headers
    assert auth.secrets() == []
