"""Read-only admin endpoints under ``/v1/admin`` (owner, admin and viewer roles)."""

from __future__ import annotations

import datetime as dt
import json
import statistics
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ira import changes
from ira.accounts import Principal
from ira.channels.deps import get_runtime, require
from ira.channels.schemas import (
    ActionRow,
    AdminUserRow,
    AuditRow,
    CallRow,
    ChangeRow,
    ChannelView,
    ConversationRow,
    InviteView,
    MessageRow,
    ModelUsage,
    Overview,
    TokenRow,
    ToolDetail,
)
from ira.runtime import Runtime

router = APIRouter(prefix="/v1/admin", tags=["admin"])
reader = require("admin.read")


def start_of_today() -> float:
    return dt.datetime.combine(dt.date.today(), dt.time()).timestamp()


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 3)
    cuts = statistics.quantiles(values, n=100, method="inclusive")
    return round(cuts[int(fraction * 100) - 1], 3)


@router.get("/overview", response_model=Overview, summary="Today at a glance")
def overview(_: Principal = Depends(reader), runtime: Runtime = Depends(get_runtime)) -> Overview:
    since = start_of_today()
    store = runtime.store
    calls = store.query("SELECT * FROM calls WHERE at >= ?", (since,))
    latencies = [c["seconds"] for c in calls if c["ok"]]
    models: dict[Any, dict[str, Any]] = {}
    for call in calls:
        entry = models.setdefault(call["model"], {"calls": 0, "failures": 0, "cost": 0.0, "s": []})
        entry["calls"] += 1
        entry["failures"] += 0 if call["ok"] else 1
        entry["cost"] += call["cost_usd"] or 0.0
        entry["s"].append(call["seconds"])
    actions = store.query(
        "SELECT status, COUNT(*) AS n FROM pending_actions WHERE created_at >= ? GROUP BY status",
        (since,),
    )
    conversations = store.one(
        "SELECT COUNT(*) AS n FROM conversations WHERE last_at >= ?", (since,)
    )
    return Overview(
        since=since,
        calls=len(calls),
        failures=sum(1 for c in calls if not c["ok"]),
        cost_usd=round(sum(c["cost_usd"] or 0.0 for c in calls), 6),
        input_tokens=sum(c["input_tokens"] for c in calls),
        output_tokens=sum(c["output_tokens"] for c in calls),
        latency_p50=_percentile(latencies, 0.50),
        latency_p95=_percentile(latencies, 0.95),
        by_model=[
            ModelUsage(
                model=model,
                calls=e["calls"],
                failures=e["failures"],
                cost_usd=round(e["cost"], 6),
                avg_seconds=round(sum(e["s"]) / len(e["s"]), 3),
            )
            for model, e in sorted(models.items(), key=lambda kv: -kv[1]["calls"])
        ],
        actions={row["status"]: row["n"] for row in actions},
        conversations=conversations["n"] if conversations else 0,
        users=runtime.accounts.count(),
    )


@router.get("/calls", response_model=list[CallRow], summary="Model calls, newest first")
def calls(
    limit: int = Query(50, ge=1, le=500),
    before_id: int | None = Query(None, description="Page: only calls older than this id."),
    _: Principal = Depends(reader),
    runtime: Runtime = Depends(get_runtime),
) -> list[CallRow]:
    rows = runtime.store.query(
        "SELECT * FROM calls WHERE id < ? ORDER BY id DESC LIMIT ?",
        (before_id if before_id is not None else 2**62, limit),
    )
    return [CallRow(**{**dict(r), "ok": bool(r["ok"])}) for r in rows]


@router.get("/conversations", response_model=list[ConversationRow], summary="Recent conversations")
def conversations(
    limit: int = Query(50, ge=1, le=500),
    before: float | None = Query(None, description="Page: only conversations active before this."),
    _: Principal = Depends(reader),
    runtime: Runtime = Depends(get_runtime),
) -> list[ConversationRow]:
    return [
        ConversationRow(**{k: r[k] for k in ConversationRow.model_fields})
        for r in runtime.conversations.recent(limit, before)
    ]


@router.get(
    "/conversations/{conversation_id}",
    response_model=list[MessageRow],
    summary="One conversation's messages, including tool calls",
)
def conversation(
    conversation_id: str, _: Principal = Depends(reader), runtime: Runtime = Depends(get_runtime)
) -> list[MessageRow]:
    if not runtime.conversations.exists(conversation_id):
        raise HTTPException(404, detail="no such conversation")
    return [MessageRow(**m) for m in runtime.conversations.transcript(conversation_id)]


@router.get("/actions", response_model=list[ActionRow], summary="Proposed actions and outcomes")
def actions(
    status: str | None = Query(None, description="pending, executed, failed, expired, ..."),
    limit: int = Query(50, ge=1, le=500),
    _: Principal = Depends(reader),
    runtime: Runtime = Depends(get_runtime),
) -> list[ActionRow]:
    if status:
        rows = runtime.store.query(
            "SELECT * FROM pending_actions WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )
    else:
        rows = runtime.store.query(
            "SELECT * FROM pending_actions ORDER BY created_at DESC LIMIT ?", (limit,)
        )
    out = []
    for row in rows:
        item = dict(row)
        item["params"] = json.loads(row["params"])
        item["result"] = json.loads(row["result"]) if row["result"] else None
        out.append(ActionRow(**item))
    return out


def tool_detail(runtime: Runtime, name: str) -> ToolDetail:
    tool = runtime.registry.get(name)
    assert tool is not None
    return ToolDetail(
        kind=tool.kind,
        enabled=runtime.registry.is_enabled(tool.name),
        confirm_roles=(
            list(runtime.guard.confirm_roles_for(tool.name)) if tool.kind == "action" else None
        ),
        **tool.schema(),
    )


@router.get("/tools", response_model=list[ToolDetail], summary="Registered tools and schemas")
def tools(
    _: Principal = Depends(reader), runtime: Runtime = Depends(get_runtime)
) -> list[ToolDetail]:
    return [tool_detail(runtime, t.name) for t in runtime.registry]


@router.get("/channels", response_model=list[ChannelView], summary="Channel status")
def channels(
    _: Principal = Depends(reader), runtime: Runtime = Depends(get_runtime)
) -> list[ChannelView]:
    settings = runtime.settings
    paired = runtime.store.one("SELECT COUNT(*) AS n FROM telegram_chats")
    telegram = dict(runtime.channel_state.get("telegram", {}))
    telegram["paired_chats"] = paired["n"] if paired else 0
    return [
        ChannelView(
            name="http",
            enabled=True,
            detail={"host": settings.channels.http.host, "port": settings.channels.http.port},
        ),
        ChannelView(
            name="web",
            enabled=True,
            detail={
                "stt": getattr(runtime.stt, "name", None),
                "tts": getattr(runtime.tts, "name", None),
            },
        ),
        ChannelView(name="telegram", enabled=settings.channels.telegram.enabled, detail=telegram),
    ]


@router.get("/audit", response_model=list[AuditRow], summary="Action audit log, newest first")
def audit(
    limit: int = Query(100, ge=1, le=1000),
    _: Principal = Depends(reader),
    runtime: Runtime = Depends(get_runtime),
) -> list[AuditRow]:
    return [AuditRow(**row) for row in runtime.guard.audit(limit)]


@router.get("/users", response_model=list[AdminUserRow], summary="Accounts (no password hashes)")
def users(
    _: Principal = Depends(reader), runtime: Runtime = Depends(get_runtime)
) -> list[AdminUserRow]:
    return [AdminUserRow(**u.public(), has_pin=u.has_pin) for u in runtime.accounts.users()]


def invite_view(runtime: Runtime, invite: Any) -> InviteView:
    return InviteView(
        id=invite.id,
        email=invite.email,
        role=invite.role,
        created_by=invite.created_by,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        state=invite.state(runtime.accounts.clock()),
    )


@router.get(
    "/users/invites", response_model=list[InviteView], summary="Open invitations (owner only)"
)
def invites(
    _: Principal = Depends(require("users")), runtime: Runtime = Depends(get_runtime)
) -> list[InviteView]:
    return [invite_view(runtime, i) for i in runtime.accounts.invites()]


@router.get("/tokens", response_model=list[TokenRow], summary="API tokens (no token values)")
def tokens(
    _: Principal = Depends(reader), runtime: Runtime = Depends(get_runtime)
) -> list[TokenRow]:
    return [TokenRow(**t) for t in runtime.accounts.tokens()]


@router.get("/changes", response_model=list[ChangeRow], summary="Console changes, newest first")
def change_log(
    limit: int = Query(100, ge=1, le=1000),
    before_id: int | None = Query(None, description="Page: only changes older than this id."),
    _: Principal = Depends(reader),
    runtime: Runtime = Depends(get_runtime),
) -> list[ChangeRow]:
    return [ChangeRow(**row) for row in changes.recent(runtime.store, limit, before_id)]
