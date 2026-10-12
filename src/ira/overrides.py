"""Settings changed from the admin console, kept in the database on top of ``ira.yaml``.

``ira.yaml`` stays the source of structure. The console can only:

* switch tools off and on;
* reorder a tier's fallback chain (the same models, in another order);
* rename the assistant and choose the text-to-speech voice.

Overrides are applied when the runtime is built and at once when they change.
An override that no longer fits the YAML (a tier whose models were edited) is
ignored with a warning rather than guessed at.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from ira.assistant import NAME_SETTING

if TYPE_CHECKING:
    from ira.runtime import Runtime

log = logging.getLogger("ira.overrides")

TOOLS_DISABLED = "tools.disabled"
TIER_ORDER = "models.tier_order"
TTS_VOICE = "voice.tts.voice"
DEFAULT_VOICES = {"polly": "Joanna", "openai": "alloy", "fake": "demo"}


class OverrideError(ValueError):
    pass


def _load(runtime: Runtime, key: str, default: Any) -> Any:
    raw = runtime.store.get_setting(key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        log.warning("ignoring an unreadable override %s", key)
        return default


def apply(runtime: Runtime) -> None:
    for name in _load(runtime, TOOLS_DISABLED, []):
        if name in runtime.registry:
            runtime.registry.set_enabled(name, False)
    for tier, order in _load(runtime, TIER_ORDER, {}).items():
        if _fits(runtime, tier, order):
            runtime.gateway.tiers[tier] = list(order)
        else:
            log.warning("ignoring the saved order for tier '%s': ira.yaml changed it", tier)
    voice = runtime.store.get_setting(TTS_VOICE)
    if voice and hasattr(runtime.tts, "voice"):
        runtime.tts.voice = voice  # type: ignore[union-attr]


# Tools.


def set_tool_enabled(runtime: Runtime, name: str, enabled: bool) -> None:
    runtime.registry.set_enabled(name, enabled)
    known = [n for n in sorted(runtime.registry.disabled()) if n in runtime.registry]
    runtime.store.set_setting(TOOLS_DISABLED, json.dumps(known))


# Model chains.


def configured_chain(runtime: Runtime, tier: str) -> list[str]:
    return list(runtime.settings.models.tiers.get(tier, []))


def _fits(runtime: Runtime, tier: str, order: Any) -> bool:
    configured = configured_chain(runtime, tier)
    return isinstance(order, list) and bool(configured) and sorted(order) == sorted(configured)


def tier_override(runtime: Runtime, tier: str) -> list[str] | None:
    order = _load(runtime, TIER_ORDER, {}).get(tier)
    return list(order) if _fits(runtime, tier, order) else None


def set_tier_order(runtime: Runtime, tier: str, order: list[str] | None) -> list[str]:
    """Save a new order for a tier (None goes back to ira.yaml). Returns the chain in use."""
    configured = configured_chain(runtime, tier)
    if not configured:
        raise OverrideError(f"unknown tier '{tier}'")
    saved = _load(runtime, TIER_ORDER, {})
    if order is None or order == configured:
        saved.pop(tier, None)
        chain = configured
    else:
        if not _fits(runtime, tier, order) or len(set(order)) != len(order):
            raise OverrideError(
                "the new order must list exactly the models ira.yaml gives this tier"
            )
        saved[tier] = list(order)
        chain = list(order)
    runtime.store.set_setting(TIER_ORDER, json.dumps(saved))
    runtime.gateway.tiers[tier] = chain
    return chain


# Name and voice.


def default_voice(runtime: Runtime) -> str | None:
    cfg = runtime.settings.voice.tts
    return cfg.voice or DEFAULT_VOICES.get(cfg.type)


def current_voice(runtime: Runtime) -> str | None:
    return getattr(runtime.tts, "voice", None)


def set_voice(runtime: Runtime, voice: str | None) -> str | None:
    if not hasattr(runtime.tts, "voice"):
        raise OverrideError("text-to-speech is off in ira.yaml, so there is no voice to choose")
    cleaned = " ".join((voice or "").split())[:64]
    if cleaned:
        runtime.store.set_setting(TTS_VOICE, cleaned)
    else:
        runtime.store.delete_setting(TTS_VOICE)
    runtime.tts.voice = cleaned or default_voice(runtime)  # type: ignore[union-attr]
    return current_voice(runtime)


def set_name(runtime: Runtime, name: str | None) -> str:
    if name is None or not name.strip():
        runtime.store.delete_setting(NAME_SETTING)
        return runtime.assistant.name
    try:
        return runtime.assistant.rename(name)
    except ValueError as exc:
        raise OverrideError(str(exc)) from None


def name_overridden(runtime: Runtime) -> bool:
    return runtime.store.get_setting(NAME_SETTING) is not None


def voice_overridden(runtime: Runtime) -> bool:
    return runtime.store.get_setting(TTS_VOICE) is not None
