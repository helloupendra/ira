"""Paged lists: X-Has-More at the boundary, and cursors that survive ties."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ira.channels.http import create_app

from .conftest import make_runtime

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret

PAGED_ROUTES = [
    "/v1/admin/calls",
    "/v1/admin/conversations",
    "/v1/admin/actions",
    "/v1/admin/changes",
    "/v1/admin/audit",
    "/v1/admin/sessions",
    "/v1/me/sessions",
    "/v1/conversations",
]


@pytest.fixture
def world(registry):
    runtime = make_runtime(registry=registry)
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    session, _ = runtime.accounts.start_session(owner)
    with TestClient(create_app(runtime, start_channels=False)) as client:
        yield client, {"Authorization": f"Bearer {session}"}, runtime, owner


def fill(runtime, owner, n: int) -> None:
    """n rows in every paged table, all of them visible to the owner."""
    store = runtime.store
    for i in range(n):
        store.execute(
            "INSERT INTO calls (at, tier, purpose, model, tried, attempts, ok, seconds) "
            "VALUES (?, 'default', 'chat', 'fake:m', 'fake:m', 1, 1, 0.1)",
            (1000 + i,),
        )
        store.execute(
            "INSERT INTO conversations (id, channel, user_id, started_at, last_at) "
            "VALUES (?, 'web', ?, 1, ?)",
            (f"http:{owner.id}:c{i}", owner.id, 1000 + i),
        )
        store.execute(
            "INSERT INTO pending_actions (id, tool, params, summary, created_at, expires_at, "
            "status) VALUES (?, 'refund', '{}', 'Refund', ?, ?, 'executed')",
            (f"act_{i}", 1000 + i, 1120 + i),
        )
        store.execute(
            "INSERT INTO change_log (at, actor, what) VALUES (?, 'owner@example.com', 'x')",
            (1000 + i,),
        )
        store.execute(
            "INSERT INTO audit_log (at, outcome, actor) VALUES (?, 'pin_set', 'owner@example.com')",
            (1000 + i,),
        )
    for _ in range(n - 1):  # the test client's own session makes n
        runtime.accounts.start_session(owner)


@pytest.mark.parametrize("route", PAGED_ROUTES)
def test_x_has_more_is_right_at_the_boundary(world, route):
    client, headers, runtime, owner = world
    fill(runtime, owner, 3)
    exact = client.get(f"{route}?limit=3", headers=headers)
    assert len(exact.json()) == 3 and exact.headers["X-Has-More"] == "false", route
    short = client.get(f"{route}?limit=2", headers=headers)
    assert len(short.json()) == 2 and short.headers["X-Has-More"] == "true", route
    roomy = client.get(f"{route}?limit=4", headers=headers)
    assert len(roomy.json()) == 3 and roomy.headers["X-Has-More"] == "false", route


@pytest.mark.parametrize("route", PAGED_ROUTES)
def test_every_paged_route_documents_the_header(world, route):
    client = world[0]
    spec = client.get("/v1/openapi.json").json()
    ok = spec["paths"][route]["get"]["responses"]["200"]
    assert ok["headers"]["X-Has-More"]["schema"]["enum"] == ["true", "false"], route
    assert ok["content"]["application/json"]["schema"]["type"] == "array", route


def walk(client, headers, route: str, cursor) -> list[str]:
    """Every id, one row per page, following the cursor the last row gives."""
    seen: list[str] = []
    url = f"{route}?limit=1"
    while True:
        response = client.get(url, headers=headers)
        rows = response.json()
        seen += [str(row["id"]) for row in rows]
        if response.headers["X-Has-More"] == "false":
            return seen
        url = f"{route}?limit=1&{cursor(rows[-1])}"


def test_conversation_pages_neither_skip_nor_repeat_rows_that_tie(world):
    client, headers, runtime, owner = world
    for name, last_at in [("a", 2000), ("b", 2000), ("c", 2000), ("old", 1000)]:
        runtime.store.execute(
            "INSERT INTO conversations (id, channel, user_id, started_at, last_at) "
            "VALUES (?, 'web', ?, 1, ?)",
            (f"http:{owner.id}:{name}", owner.id, last_at),
        )

    def cursor(row):
        return f"before={row['last_at']}&before_id={row['id']}"

    admin = walk(client, headers, "/v1/admin/conversations", cursor)
    assert admin == [f"http:{owner.id}:{n}" for n in ("c", "b", "a", "old")]
    mine = walk(client, headers, "/v1/conversations", cursor)
    assert mine == ["c", "b", "a", "old"]

    # The old parameter alone still works: strictly older than before.
    older = client.get("/v1/conversations?before=2000", headers=headers).json()
    assert [row["id"] for row in older] == ["old"]


def test_action_pages_neither_skip_nor_repeat_rows_that_tie(world):
    client, headers, runtime, _ = world
    for action_id in ("act_a", "act_b", "act_c"):
        runtime.store.execute(
            "INSERT INTO pending_actions (id, tool, params, summary, created_at, expires_at, "
            "status) VALUES (?, 'refund', '{}', 'Refund', 1000, 1120, 'executed')",
            (action_id,),
        )

    def cursor(row):
        return f"before={row['created_at']}&before_id={row['id']}"

    assert walk(client, headers, "/v1/admin/actions", cursor) == ["act_c", "act_b", "act_a"]


def test_session_pages_neither_skip_nor_repeat_rows_that_tie(world):
    client, headers, runtime, owner = world
    for _ in range(2):
        runtime.accounts.start_session(owner)
    # Every session last used at the same moment, the listing's own included.
    runtime.accounts.clock = lambda: 5000.0
    runtime.store.execute("UPDATE sessions SET last_seen_at = 5000, created_at = 4000")
    runtime.store.execute("UPDATE sessions SET expires_at = 10000")

    def cursor(row):
        return f"before={row['last_used_at']}&before_id={row['id']}"

    ids = {row["id"] for row in runtime.accounts.sessions()}
    for route in ("/v1/me/sessions", "/v1/admin/sessions"):
        walked = walk(client, headers, route, cursor)
        assert sorted(walked) == sorted(ids) and len(walked) == 3, route
        assert walked == sorted(ids, reverse=True), route


def test_audit_pages_by_id(world):
    client, headers, runtime, owner = world
    fill(runtime, owner, 3)
    first = client.get("/v1/admin/audit?limit=2", headers=headers).json()
    rest = client.get(f"/v1/admin/audit?before_id={first[-1]['id']}", headers=headers)
    assert [r["id"] for r in rest.json()] == [first[-1]["id"] - 1]
    assert rest.headers["X-Has-More"] == "false"
