"""The one-time setup code that guards the owner account on a new install.

It lives in the database, not in memory, so a restart keeps a link that was
already handed out: the same code works until the owner exists or 24 hours
pass. ``ira setup --new-code`` replaces it.

Keeping the code itself (not a hash) lets ``ira serve`` print the same link
again. It adds no exposure: anyone who can read the database can already
create the owner with ``ira setup``.
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable

from ira.store import Store

KEY = "setup_code"
TTL_SECONDS = 24 * 3600


def make() -> str:
    return "-".join(secrets.token_hex(2).upper() for _ in range(3))


def current(store: Store, clock: Callable[[], float] = time.time) -> str | None:
    """The code, while it is unused and under 24 hours old."""
    raw = store.get_setting(KEY)
    if not raw:
        return None
    try:
        saved = json.loads(raw)
        code, expires_at = str(saved["code"]), float(saved["expires_at"])
    except (ValueError, KeyError, TypeError):
        return None
    return code if clock() < expires_at else None


def renew(store: Store, clock: Callable[[], float] = time.time) -> str:
    """A new code, replacing any earlier one."""
    code = make()
    store.set_setting(KEY, json.dumps({"code": code, "expires_at": clock() + TTL_SECONDS}))
    return code


def retire(store: Store) -> None:
    store.delete_setting(KEY)
