from __future__ import annotations

import httpx
import pytest

from ira.models.base import ChatResponse, Message, ProviderError, StreamDone, TextDelta, Usage
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
    row = store.one("SELECT * FROM calls")
    assert (row["tried"], row["attempts"], row["ok"], row["model"]) == ("a:m,b:m", 2, 1, "b:m")


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
    row = store.one("SELECT * FROM calls")
    assert (row["ok"], row["attempts"], row["error_kind"]) == (0, 2, "capacity")


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
