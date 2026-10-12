"""Settings changed from the admin console, kept in the database on top of ``ira.yaml``.

``ira.yaml`` stays the source of structure. The console can only:

* switch tools off and on;
* reorder a tier's fallback chain (the same models, in another order).

Overrides are applied when the runtime is built and at once when they change.
An override that no longer fits the YAML (a tier whose models were edited) is
ignored with a warning rather than guessed at.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ira.runtime import Runtime

log = logging.getLogger("ira.overrides")

TOOLS_DISABLED = "tools.disabled"
TIER_ORDER = "models.tier_order"


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
