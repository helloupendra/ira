"""Settings changed from the admin console, kept in the database on top of ``ira.yaml``.

``ira.yaml`` stays the source of structure. The console can switch tools off
and on. Overrides are applied when the runtime is built and at once when they
change.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ira.runtime import Runtime

log = logging.getLogger("ira.overrides")

TOOLS_DISABLED = "tools.disabled"


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


# Tools.


def set_tool_enabled(runtime: Runtime, name: str, enabled: bool) -> None:
    runtime.registry.set_enabled(name, enabled)
    known = [n for n in sorted(runtime.registry.disabled()) if n in runtime.registry]
    runtime.store.set_setting(TOOLS_DISABLED, json.dumps(known))
