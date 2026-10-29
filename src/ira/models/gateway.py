"""The LLM gateway: fallback chains per tier, cool-downs, cost, and a call log.

A tier ("default", "fast", ...) is an ordered list of model references in the
form ``provider:model``. A call tries them in order and moves to the next one
on any error, timeout or capacity refusal. A model that just failed is put on
a short cool-down and tried last until it expires, so one bad model does not
add its timeout to every request.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from ira.models.base import (
    REQUEST_ERRORS,
    ChatProvider,
    ChatResponse,
    Message,
    ProviderError,
    StreamDone,
    StreamEvent,
    TextDelta,
    Usage,
)
from ira.store import Store

log = logging.getLogger("ira.gateway")

PROBE_PROMPT = "This is a connection test. Reply with the single word: ready"

# Why a model is cooling down, in words of our own. A provider's error text can
# quote the request (and so the prompt), so it is never shown.
COOLING_MESSAGES = {
    "capacity": "The provider is busy or rate-limited.",
    "timeout": "No answer in time.",
    "auth": "The provider refused the key.",
    "bad_request": "The provider rejected the request.",
    "server": "The provider answered with an error.",
    "network": "The provider could not be reached.",
    "error": "The call failed.",
}


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens. Cached input, read from or written to the provider's
    cache, has its own rates: unset, half the input price and a quarter more than it, the
    most the big providers charge, so a cost is never under-counted."""

    input: float
    output: float
    cached_input: float | None = None
    cache_write: float | None = None

    def of(self, usage: Usage) -> float:
        read = self.cached_input if self.cached_input is not None else self.input * 0.5
        write = self.cache_write if self.cache_write is not None else self.input * 1.25
        plain = max(0, usage.input_tokens - usage.cached_input_tokens - usage.cache_write_tokens)
        return (
            plain * self.input
            + usage.cached_input_tokens * read
            + usage.cache_write_tokens * write
            + usage.output_tokens * self.output
        ) / 1_000_000


class GatewayError(Exception):
    """Every model in the chain failed."""

    def __init__(self, tier: str, errors: list[tuple[str, ProviderError]]) -> None:
        self.tier = tier
        self.errors = errors
        detail = "; ".join(f"{ref}: {err.kind}" for ref, err in errors) or "no models configured"
        super().__init__(f"all models in tier '{tier}' failed ({detail})")


def split_ref(ref: str) -> tuple[str, str]:
    provider, sep, model = ref.partition(":")
    if not sep or not provider or not model:
        raise ValueError(f"model reference '{ref}' must look like 'provider:model'")
    return provider, model


class Gateway:
    def __init__(
        self,
        providers: dict[str, ChatProvider],
        tiers: dict[str, list[str]],
        *,
        prices: dict[str, Price] | None = None,
        store: Store | None = None,
        cooldown_seconds: float = 60.0,
        timeout_seconds: float = 60.0,
        max_tokens: int = 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        for tier, refs in tiers.items():
            for ref in refs:
                provider, _ = split_ref(ref)
                if provider not in providers:
                    raise ValueError(f"tier '{tier}' uses unknown provider '{provider}'")
        self.providers = providers
        # A copy: the console may reorder a chain without touching the parsed config.
        self.tiers = {tier: list(refs) for tier, refs in tiers.items()}
        self.prices = prices or {}
        self.store = store
        self.cooldown_seconds = cooldown_seconds
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.clock = clock
        self._cool_until: dict[str, float] = {}
        self._cool_reason: dict[str, tuple[str, int | None]] = {}  # ref -> (kind, status)

    def chain(self, tier: str) -> list[str]:
        """The tier's models in the order they will be tried right now."""
        if tier not in self.tiers:
            raise KeyError(f"unknown tier '{tier}'")
        now = self.clock()
        refs = self.tiers[tier]
        ready = [r for r in refs if self._cool_until.get(r, 0.0) <= now]
        cooling = [r for r in refs if self._cool_until.get(r, 0.0) > now]
        # A chain never runs dry: cooling models are still tried, just last.
        return ready + cooling

    def cooling(self) -> dict[str, float]:
        """Models on a cool-down right now, with the seconds left."""
        now = self.clock()
        return {
            ref: round(until - now, 1) for ref, until in self._cool_until.items() if until > now
        }

    def cooling_reasons(self) -> dict[str, dict[str, Any]]:
        """Why each cooling model is cooling: its last error's kind and HTTP status, and a
        short message of our own. Never the provider's text, a key or a prompt."""
        out = {}
        for ref in self.cooling():
            kind, status = self._cool_reason.get(ref, ("error", None))
            message = COOLING_MESSAGES.get(kind, COOLING_MESSAGES["error"])
            out[ref] = {
                "error_kind": kind,
                "status": status,
                "message": f"{message[:-1]} (HTTP {status})." if status else message,
            }
        return out

    def _warm(self, ref: str) -> None:
        self._cool_until.pop(ref, None)
        self._cool_reason.pop(ref, None)

    async def probe(self, ref: str) -> tuple[ChatResponse | None, ProviderError | None, float]:
        """Ask one model a fixed short question, outside any chain.

        Used by the console's "test this model". The call is logged (it costs
        money) with purpose "test". A success lifts the model's cool-down; a
        failure does not add one, so a test never changes live routing for the worse.
        """
        provider_name, model = split_ref(ref)
        if provider_name not in self.providers:
            raise KeyError(provider_name)
        started = time.monotonic()
        response: ChatResponse | None = None
        error: ProviderError | None = None
        try:
            response = await asyncio.wait_for(
                self.providers[provider_name].chat(
                    model,
                    [Message(role="user", content=PROBE_PROMPT)],
                    None,
                    max_tokens=min(self.max_tokens, 64),
                    timeout=self.timeout_seconds,
                ),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            error = ProviderError(f"{ref}: no answer in {self.timeout_seconds}s", kind="timeout")
        except ProviderError as exc:
            error = exc
        seconds = round(time.monotonic() - started, 3)
        if response is not None:
            response.model = ref
            response.cost_usd = self.cost(ref, response.usage)
            self._warm(ref)
        self._record(
            _request(),
            "(test)",
            "test",
            [ref],
            ref,
            response,
            error.kind if error else None,
            started,
        )
        return response, error, seconds

    def cost(self, ref: str, usage: Usage) -> float | None:
        """What a call cost, or None when it is not known: no price for the model, or the
        provider did not say how many tokens it used. Never $0 for "we do not know"."""
        price = self.prices.get(ref)
        if price is None or not usage.known:
            return None
        return price.of(usage)

    def _cool_down(self, ref: str, error: ProviderError) -> None:
        if error.kind in REQUEST_ERRORS:
            # One too-long or malformed request is that request's problem: the model is
            # fine for everyone else, so it is not benched.
            log.warning("model %s refused one request (%s)", ref, error.kind)
            return
        seconds = self.cooldown_seconds
        if error.retry_after:
            seconds = min(max(seconds, error.retry_after), 10 * self.cooldown_seconds)
        self._cool_until[ref] = self.clock() + seconds
        self._cool_reason[ref] = (error.kind, error.status)
        log.warning("model %s failed (%s); cooling down %.0fs", ref, error.kind, seconds)

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        *,
        tier: str = "default",
        purpose: str = "chat",
    ) -> ChatResponse:
        request = _request()
        errors: list[tuple[str, ProviderError]] = []
        tried: list[str] = []
        for ref in self.chain(tier):
            provider_name, model = split_ref(ref)
            tried.append(ref)
            started = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    self.providers[provider_name].chat(
                        model,
                        messages,
                        tools,
                        max_tokens=self.max_tokens,
                        timeout=self.timeout_seconds,
                    ),
                    timeout=self.timeout_seconds,
                )
            except TimeoutError:
                error = ProviderError(
                    f"{ref}: no answer in {self.timeout_seconds}s", kind="timeout"
                )
                errors.append((ref, error))
                self._cool_down(ref, error)
                self._record(request, tier, purpose, tried, ref, None, error.kind, started)
                continue
            except ProviderError as error:
                errors.append((ref, error))
                self._cool_down(ref, error)
                self._record(request, tier, purpose, tried, ref, None, error.kind, started)
                continue
            except BaseException:  # the caller gave up (cancelled): the attempt still counts
                self._record(request, tier, purpose, tried, ref, None, "abandoned", started)
                raise
            self._warm(ref)
            response.model = ref
            response.attempts = len(tried)
            response.cost_usd = self.cost(ref, response.usage)
            self._record(request, tier, purpose, tried, ref, response, None, started)
            return response
        if not tried:
            self._record(request, tier, purpose, tried, None, None, "no_models", time.monotonic())
        raise GatewayError(tier, errors)

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        *,
        tier: str = "default",
        purpose: str = "chat",
    ) -> AsyncIterator[StreamEvent]:
        """Stream from the first model that answers.

        Falling back is only possible until the first text reaches the caller;
        after that, a failure is raised rather than mixing two models' words.
        """
        request = _request()
        errors: list[tuple[str, ProviderError]] = []
        tried: list[str] = []
        for ref in self.chain(tier):
            provider_name, model = split_ref(ref)
            tried.append(ref)
            started = time.monotonic()
            events = self.providers[provider_name].stream(
                model, messages, tools, max_tokens=self.max_tokens, timeout=self.timeout_seconds
            )
            emitted = False
            recorded = False
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(
                            events.__anext__(), timeout=self.timeout_seconds
                        )
                    except StopAsyncIteration:
                        raise ProviderError(f"{ref}: stream ended early", kind="server") from None
                    except TimeoutError:
                        raise ProviderError(
                            f"{ref}: stream stalled for {self.timeout_seconds}s", kind="timeout"
                        ) from None
                    if isinstance(event, TextDelta):
                        emitted = True
                        yield event
                    elif isinstance(event, StreamDone):
                        response = event.response
                        response.model = ref
                        response.attempts = len(tried)
                        response.cost_usd = self.cost(ref, response.usage)
                        self._warm(ref)
                        self._record(request, tier, purpose, tried, ref, response, None, started)
                        recorded = True
                        yield StreamDone(response)
                        return
            except ProviderError as error:
                errors.append((ref, error))
                self._cool_down(ref, error)
                self._record(request, tier, purpose, tried, ref, None, error.kind, started)
                recorded = True
                if emitted:
                    raise GatewayError(tier, errors) from error
            finally:
                if not recorded:  # cut off: the caller stopped reading, or was cancelled
                    self._record(request, tier, purpose, tried, ref, None, "abandoned", started)
                await _aclose(events)
        if not tried:
            self._record(request, tier, purpose, tried, None, None, "no_models", time.monotonic())
        raise GatewayError(tier, errors)

    def _record(
        self,
        request: str,
        tier: str,
        purpose: str,
        tried: list[str],
        ref: str | None,
        response: ChatResponse | None,
        error_kind: str | None,
        started: float,
    ) -> None:
        """One row per attempt, however it ended: answered, failed, timed out, or cut off
        ("abandoned"). The attempts of one request share its id. A cost that is not known
        (no price, no token count, a failed or cut-off attempt) is stored as unknown, not 0."""
        if self.store is None:
            return
        usage = response.usage if response else Usage(known=False)
        self.store.execute(
            "INSERT INTO calls (at, request, tier, purpose, model, tried, attempts, ok, "
            "error_kind, seconds, input_tokens, output_tokens, cached_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                time.time(),
                request,
                tier,
                purpose,
                ref,
                ",".join(tried),
                len(tried),
                1 if response else 0,
                error_kind,
                round(time.monotonic() - started, 3),
                usage.input_tokens,
                usage.output_tokens,
                usage.cached_input_tokens,
                response.cost_usd if response else None,
            ),
        )


def _request() -> str:
    """The id the attempts of one request share in the cost log."""
    return secrets.token_hex(6)


async def _aclose(events: Any) -> None:
    close = getattr(events, "aclose", None)
    if close is not None:
        try:
            await close()
        except Exception:  # closing a broken stream must not hide the real error
            pass
