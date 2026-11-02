from __future__ import annotations

import asyncio

import httpx
import pytest

from ira.models.base import (
    ChatResponse,
    Message,
    ProviderError,
    StreamDone,
    TextDelta,
    ToolCall,
    Usage,
)
from ira.models.fake import ScriptedProvider
from ira.models.gateway import Gateway, GatewayError, Price
from ira.models.http import BearerAuth, HttpClient
from ira.store import Store

pytestmark = pytest.mark.anyio

HELLO = [Message(role="user", content="hello")]


def gateway(store: Store, clock=None, **providers) -> Gateway:
    refs = [f"{name}:m" for name in providers]
    kwargs = {"clock": clock} if clock else {}
    return Gateway(providers, {"default": refs}, store=store, cooldown_seconds=60, **kwargs)


async def test_falls_back_to_the_next_model_on_capacity_refusal(store):
    first = ScriptedProvider([ProviderError("busy", kind="capacity", status=429)])
    second = ScriptedProvider(["from the second model"])
    gw = gateway(store, a=first, b=second)

    response = await gw.chat(HELLO)

    assert response.text == "from the second model"
    assert response.model == "b:m"
    assert response.attempts == 2
    # One row per attempt: the one that failed counts against its own model.
    rows = store.query("SELECT * FROM calls ORDER BY id")
    assert [(r["model"], r["tried"], r["attempts"], r["ok"], r["error_kind"]) for r in rows] == [
        ("a:m", "a:m", 1, 0, "capacity"),
        ("b:m", "a:m,b:m", 2, 1, None),
    ]
    assert rows[0]["request"] == rows[1]["request"] and rows[0]["cost_usd"] is None


async def test_falls_back_on_timeout(store):
    slow = ScriptedProvider(["too late"], delay=1.0)
    fast = ScriptedProvider(["in time"])
    gw = Gateway({"slow": slow, "fast": fast}, {"default": ["slow:m", "fast:m"]}, store=store)
    gw.timeout_seconds = 0.05

    response = await gw.chat(HELLO)

    assert response.text == "in time"


async def test_failing_model_cools_down_then_returns(store, clock):
    first = ScriptedProvider([ProviderError("down", kind="server"), "first is back"])
    second = ScriptedProvider(["second answers", "second again"])
    gw = gateway(store, clock, a=first, b=second)

    await gw.chat(HELLO)
    assert gw.chain("default") == ["b:m", "a:m"]  # a is cooling: tried last

    response = await gw.chat(HELLO)
    assert response.model == "b:m"
    assert len(first.calls) == 1  # not retried during the cool-down

    clock.advance(61)
    assert gw.chain("default") == ["a:m", "b:m"]
    assert (await gw.chat(HELLO)).text == "first is back"


async def test_all_models_failing_raises_and_is_logged(store):
    gw = gateway(
        store,
        a=ScriptedProvider([ProviderError("x", kind="auth")]),
        b=ScriptedProvider([ProviderError("y", kind="capacity")]),
    )
    with pytest.raises(GatewayError) as caught:
        await gw.chat(HELLO)
    assert [ref for ref, _ in caught.value.errors] == ["a:m", "b:m"]
    rows = store.query("SELECT ok, attempts, error_kind FROM calls ORDER BY id")
    assert [tuple(r) for r in rows] == [(0, 1, "auth"), (0, 2, "capacity")]


async def test_cost_comes_from_the_price_table(store):
    provider = ScriptedProvider([ChatResponse(text="ok", usage=Usage(1000, 500))])
    gw = Gateway(
        {"p": provider},
        {"default": ["p:m"]},
        prices={"p:m": Price(input=1.0, output=2.0)},
        store=store,
    )
    response = await gw.chat(HELLO)
    assert response.cost_usd == pytest.approx(0.002)
    row = store.one("SELECT input_tokens, output_tokens, cost_usd FROM calls")
    assert tuple(row) == (1000, 500, pytest.approx(0.002))


async def test_a_cost_not_known_is_unknown_and_cached_input_is_cheaper(store):
    unreported = ChatResponse(text="ok", usage=Usage(known=False))
    cached = ChatResponse(text="ok", usage=Usage(1000, 0, cached_input_tokens=800))
    provider = ScriptedProvider([unreported, cached, cached])
    prices = {"p:m": Price(input=1.0, output=2.0, cached_input=0.1)}
    gw = Gateway({"p": provider}, {"default": ["p:m"]}, prices=prices, store=store)
    assert (await gw.chat(HELLO)).cost_usd is None  # the provider did not say: not $0
    # 200 plain at $1 and 800 cached at $0.10, per million.
    assert (await gw.chat(HELLO)).cost_usd == pytest.approx((200 * 1.0 + 800 * 0.1) / 1e6)
    gw.prices["p:m"] = Price(input=1.0, output=2.0)  # no cached price set: half, never less
    assert (await gw.chat(HELLO)).cost_usd == pytest.approx((200 * 1.0 + 800 * 0.5) / 1e6)
    costs = [r["cost_usd"] for r in store.query("SELECT cost_usd FROM calls ORDER BY id")]
    assert costs[0] is None
    assert [r["cached_tokens"] for r in store.query("SELECT cached_tokens FROM calls")] == [
        0,
        800,
        800,
    ]


async def test_a_stream_cut_off_is_still_counted(store):
    gw = gateway(store, a=ScriptedProvider(["a long answer in many words"]))
    stream = gw.stream(HELLO)
    first = await anext(stream)
    assert isinstance(first, TextDelta)
    await stream.aclose()  # the person spoke over Ira
    row = store.one("SELECT model, ok, error_kind, cost_usd FROM calls")
    assert tuple(row) == ("a:m", 0, "abandoned", None)


async def test_stream_falls_back_before_the_first_word(store):
    gw = gateway(
        store,
        a=ScriptedProvider([ProviderError("busy", kind="capacity")]),
        b=ScriptedProvider(["streamed answer"]),
    )
    events = [e async for e in gw.stream(HELLO)]
    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    done = events[-1]
    assert text == "streamed answer"
    assert isinstance(done, StreamDone) and done.response.model == "b:m"


async def test_stream_never_mixes_two_models_after_text_was_sent(store):
    class BreaksMidway:
        async def chat(self, *a, **k):  # pragma: no cover - not used
            raise AssertionError

        async def stream(self, *a, **k):
            yield TextDelta("partial ")
            raise ProviderError("connection reset", kind="network")

    backup = ScriptedProvider(["should not be used"])
    gw = gateway(store, a=BreaksMidway(), b=backup)

    received = []
    with pytest.raises(GatewayError):
        async for event in gw.stream(HELLO):
            received.append(event)
    assert [e.text for e in received] == ["partial "]
    assert backup.calls == []


async def test_an_empty_answer_moves_on_to_the_next_model(store, caplog):
    first = ScriptedProvider([ChatResponse(text=" \n")])
    second = ScriptedProvider(["from the second model"])
    gw = gateway(store, a=first, b=second)

    response = await gw.chat(HELLO)

    assert response.text == "from the second model" and response.attempts == 2
    assert "a:m gave an empty answer; trying the next model" in caplog.text
    assert gw.chain("default") == ["a:m", "b:m"]  # no cool-down: it failed this request only
    rows = store.query("SELECT model, ok, error_kind, output_tokens FROM calls ORDER BY id")
    assert [tuple(r) for r in rows] == [("a:m", 0, "empty", 1), ("b:m", 1, None, 5)]


async def test_a_streamed_empty_answer_moves_on_to_the_next_model(store):
    gw = gateway(store, a=ScriptedProvider([""]), b=ScriptedProvider(["streamed answer"]))

    events = [e async for e in gw.stream(HELLO)]

    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "streamed answer"
    assert isinstance(events[-1], StreamDone) and events[-1].response.model == "b:m"
    rows = store.query("SELECT model, ok, error_kind FROM calls ORDER BY id")
    assert [tuple(r) for r in rows] == [("a:m", 0, "empty"), ("b:m", 1, None)]


@pytest.mark.parametrize("stream", [False, True])
async def test_every_model_empty_is_a_failure(store, stream):
    gw = gateway(store, a=ScriptedProvider([""]), b=ScriptedProvider([""]))
    with pytest.raises(GatewayError) as caught:
        if stream:
            [e async for e in gw.stream(HELLO)]
        else:
            await gw.chat(HELLO)
    assert [(ref, e.kind) for ref, e in caught.value.errors] == [("a:m", "empty"), ("b:m", "empty")]


async def test_a_tool_call_without_words_is_an_answer(store):
    call = ChatResponse(text="", tool_calls=[ToolCall("c1", "order_status", "{}")])
    gw = gateway(store, a=ScriptedProvider([call]), b=ScriptedProvider(["unused"]))
    assert (await gw.chat(HELLO)).tool_calls[0].name == "order_status"


async def test_provider_errors_never_carry_the_api_key():
    key = "sk-test-0123456789abcdef"

    def handler(request: httpx.Request) -> httpx.Response:
        # Some servers echo the credential back in their error body.
        return httpx.Response(401, json={"error": f"invalid key {key}"})

    http = HttpClient(
        "https://llm.example.com/v1",
        BearerAuth(key),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ProviderError) as caught:
        await http.post_json("/chat/completions", {"model": "m"})
    assert key not in str(caught.value)
    assert caught.value.kind == "auth"


def test_unknown_provider_in_a_tier_is_a_config_error(store):
    with pytest.raises(ValueError, match="unknown provider"):
        Gateway({"a": ScriptedProvider()}, {"default": ["a:m", "missing:m"]}, store=store)


def test_providers_say_what_was_cached():
    from ira.models.base import anthropic_usage, openai_usage

    openai = openai_usage(
        {
            "prompt_tokens": 1000,
            "completion_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 600},
        }
    )
    assert (openai.input_tokens, openai.cached_input_tokens, openai.known) == (1000, 600, True)
    # Anthropic counts cache reads and writes apart from input_tokens.
    split = anthropic_usage(
        {"input_tokens": 50, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 100},
        output_tokens=30,
    )
    assert (split.input_tokens, split.cached_input_tokens, split.cache_write_tokens) == (
        1050,
        900,
        100,
    )
    assert split.output_tokens == 30
    assert not openai_usage(None).known and not anthropic_usage({}).known


class Silent:
    """A model that says nothing for a long time, as a stuck one does."""

    def __init__(self, seconds: float, words: str = "late") -> None:
        self.seconds = seconds
        self.words = words
        self.asked = 0

    async def stream(self, model, messages, tools, *, max_tokens, timeout):
        self.asked += 1
        await asyncio.sleep(self.seconds)
        yield TextDelta(self.words)
        yield StreamDone(ChatResponse(text=self.words))

    async def chat(self, model, messages, tools, *, max_tokens, timeout, tool_choice=None):
        self.asked += 1
        await asyncio.sleep(self.seconds)
        return ChatResponse(text=self.words)


def two(first: Silent, second: Silent) -> Gateway:
    return Gateway({"a": first, "b": second}, {"default": ["a:m", "b:m"]})


async def test_a_silent_first_model_gives_way_at_the_first_token_limit():
    gateway = two(Silent(5.0, "first"), Silent(0.0, "second"))
    events = [
        e
        async for e in gateway.stream(
            [Message(role="user", content="hi")], first_token_seconds=0.02
        )
    ]
    assert events[-1].response.text == "second"
    assert "a:m" in gateway.cooling()


async def test_the_last_model_gets_the_whole_timeout():
    gateway = two(Silent(5.0, "first"), Silent(0.05, "second"))
    events = [
        e
        async for e in gateway.stream(
            [Message(role="user", content="hi")], first_token_seconds=0.01
        )
    ]
    assert events[-1].response.text == "second"  # slower than the limit, and nothing else is left


async def test_a_model_that_has_begun_is_not_held_to_the_first_token_limit():
    class Slowly(Silent):
        async def stream(self, model, messages, tools, *, max_tokens, timeout):
            yield TextDelta("")  # it is calling a tool, with no words yet
            await asyncio.sleep(0.05)
            yield StreamDone(ChatResponse(text="", tool_calls=[ToolCall("c", "t", "{}")]))

    gateway = two(Slowly(0.0), Silent(0.0, "second"))
    events = [
        e
        async for e in gateway.stream(
            [Message(role="user", content="hi")], first_token_seconds=0.01
        )
    ]
    assert events[-1].response.tool_calls  # the first answered
    assert not [e for e in events if isinstance(e, TextDelta)]  # and the marker never goes out


async def test_a_whole_answer_has_its_own_limit_while_another_model_is_left():
    gateway = two(Silent(5.0, "first"), Silent(0.0, "second"))
    answer = await gateway.chat([Message(role="user", content="hi")], seconds=0.02)
    assert answer.text == "second"
