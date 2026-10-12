"""Read-only admin endpoints under ``/v1/admin`` (owner, admin and viewer roles).

The console's writes live in ``admin_write.py``.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import statistics
import zoneinfo
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ira import changes, overrides
from ira.accounts import COOKIE_DAYS, PERMISSIONS, ROLE_DESCRIPTIONS, ROLES, TOKEN_SCOPES, Principal
from ira.changes import split_actor
from ira.channels.account import SESSIONS_BEFORE, SESSIONS_BEFORE_ID, current_flag
from ira.channels.deps import COOKIE_SAMESITE, get_runtime, require
from ira.channels.paging import PAGED, page
from ira.channels.schemas import (
    ERRORS,
    ActionCounts,
    ActionRow,
    ActionRule,
    AdminSessionRow,
    AdminUserRow,
    AuditRow,
    CallRow,
    ChangeRow,
    ChannelView,
    ConversationRow,
    CostDay,
    ErrorDetail,
    InviteView,
    KeyView,
    MessageRow,
    ModelsView,
    ModelUsage,
    Overview,
    ProviderView,
    RoleView,
    SecurityView,
    ServerAddress,
    SettingsView,
    SettingValue,
    TelegramChat,
    TelegramView,
    TierView,
    TokenRow,
    ToolDetail,
    VoiceOption,
)
from ira.runtime import Runtime
from ira.tools.actions import ACTION_STATUSES
from ira.voice.voices import voices_for

router = APIRouter(prefix="/v1/admin", tags=["admin"], responses=ERRORS)
reader = require("admin.read")


def start_of_today() -> float:
    return dt.datetime.combine(dt.date.today(), dt.time()).timestamp()


def _zone_name(name: str | None) -> str | None:
    name = (name or "").strip().lstrip(":")
    if not name or name.startswith("/"):
        return None
    try:
        zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return None
    return name


def local_timezone() -> str:
    """The server's time zone: its IANA name when the system says it, else its UTC offset.

    Looks at ``TZ``, then where ``/etc/localtime`` points, then ``/etc/timezone``.
    The offset reads like ``+05:30``.
    """
    name = _zone_name(os.environ.get("TZ"))
    if name is None:
        try:
            target = os.readlink("/etc/localtime")
        except OSError:
            target = ""
        if "zoneinfo/" in target:
            name = _zone_name(target.split("zoneinfo/", 1)[1])
    if name is None:
        try:
            name = _zone_name(Path("/etc/timezone").read_text(encoding="utf-8"))
        except OSError:
            name = None
    if name is not None:
        return name
    offset = dt.datetime.now().astimezone().strftime("%z")  # +0530
    return f"{offset[:3]}:{offset[3:]}"


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
    runtime.guard.expire_overdue()
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
    questions = store.one(
        "SELECT COUNT(*) AS n FROM messages WHERE role = 'user' AND at >= ?", (since,)
    )
    return Overview(
        since=since,
        since_iso=dt.datetime.fromtimestamp(since).astimezone().isoformat(),
        timezone=local_timezone(),
        questions=questions["n"] if questions else 0,
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


BEFORE_ID_CONVERSATION = (
    "With before: the last row's id, so rows that share its last_at are neither skipped nor "
    "repeated. Ignored without before."
)


@router.get(
    "/calls",
    response_model=list[CallRow],
    summary="Model calls, newest first",
    responses=PAGED,
)
def calls(
    response: Response,
    limit: int = Query(50, ge=1, le=500),
    before_id: int | None = Query(None, description="Page: only calls older than this id."),
    _: Principal = Depends(reader),
    runtime: Runtime = Depends(get_runtime),
) -> list[CallRow]:
    rows = runtime.store.query(
        "SELECT * FROM calls WHERE id < ? ORDER BY id DESC LIMIT ?",
        (before_id if before_id is not None else 2**62, limit + 1),
    )
    return [
        CallRow(**{**dict(r), "ok": bool(r["ok"]), "tried_list": _split(r["tried"])})
        for r in page(rows, limit, response)
    ]


def _split(tried: str) -> list[str]:
    return [ref for ref in tried.split(",") if ref]


@router.get(
    "/conversations",
    response_model=list[ConversationRow],
    summary="Recent conversations",
    responses=PAGED,
)
def conversations(
    response: Response,
    limit: int = Query(50, ge=1, le=500),
    before: float | None = Query(
        None, description="Page: only conversations active before this (the last row's last_at)."
    ),
    before_id: str | None = Query(None, description=BEFORE_ID_CONVERSATION),
    _: Principal = Depends(reader),
    runtime: Runtime = Depends(get_runtime),
) -> list[ConversationRow]:
    rows = runtime.conversations.recent(limit + 1, before, before_id=before_id)
    return [
        ConversationRow(**{k: r[k] for k in ConversationRow.model_fields})
        for r in page(rows, limit, response)
    ]


NO_CONVERSATION: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorDetail, "description": "No conversation with that id"}
}


@router.get(
    "/conversations/{conversation_id}/info",
    response_model=ConversationRow,
    summary="One conversation's header: channel, who, when, turns",
    responses=NO_CONVERSATION,
)
def conversation_info(
    conversation_id: str, _: Principal = Depends(reader), runtime: Runtime = Depends(get_runtime)
) -> ConversationRow:
    row = runtime.conversations.get(conversation_id)
    if row is None:
        raise HTTPException(404, detail="no such conversation")
    return ConversationRow(**{k: row[k] for k in ConversationRow.model_fields})


@router.get(
    "/conversations/{conversation_id}",
    response_model=list[MessageRow],
    summary="One conversation's messages, including tool calls",
    responses=NO_CONVERSATION,
)
def conversation(
    conversation_id: str, _: Principal = Depends(reader), runtime: Runtime = Depends(get_runtime)
) -> list[MessageRow]:
    if not runtime.conversations.exists(conversation_id):
        raise HTTPException(404, detail="no such conversation")
    runtime.guard.expire_overdue()
    return [MessageRow(**m) for m in runtime.conversations.transcript(conversation_id)]


@router.get(
    "/actions",
    response_model=list[ActionRow],
    summary="Proposed actions and outcomes, newest first",
    responses=PAGED,
)
def actions(
    response: Response,
    status: str | None = Query(None, description="pending, executed, failed, expired, ..."),
    limit: int = Query(50, ge=1, le=500),
    before: float | None = Query(
        None, description="Page: only actions proposed before this (the last row's created_at)."
    ),
    before_id: str | None = Query(
        None,
        description="With before: the last row's id, so actions proposed at the same moment "
        "are neither skipped nor repeated. Ignored without before.",
    ),
    _: Principal = Depends(reader),
    runtime: Runtime = Depends(get_runtime),
) -> list[ActionRow]:
    runtime.guard.expire_overdue()
    where: list[str] = []
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status)
    if before is not None and before_id is not None:
        where.append("(created_at < ? OR (created_at = ? AND id < ?))")
        params += [before, before, before_id]
    elif before is not None:
        where.append("created_at < ?")
        params.append(before)
    rows = page(
        runtime.store.query(
            f"SELECT * FROM pending_actions WHERE {' AND '.join(where) or '1'} "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (*params, limit + 1),
        ),
        limit,
        response,
    )
    decisions = _decisions(runtime, [row["id"] for row in rows])
    out = []
    for row in rows:
        item = dict(row)
        item["actor"], item["channel"] = split_actor(row["actor"], row["channel"])
        item["params"] = json.loads(row["params"])
        item["result"] = json.loads(row["result"]) if row["result"] else None
        decided = decisions.get(row["id"])
        if decided:
            item["decided_by"], item["decided_channel"], item["decided_at"] = decided
        out.append(ActionRow(**item))
    return out


@router.get(
    "/actions/counts",
    response_model=ActionCounts,
    summary="Proposed actions by status, over all time or since a moment",
)
def action_counts(
    since: float | None = Query(
        None, description="Only actions proposed at or after this (epoch seconds)."
    ),
    _: Principal = Depends(reader),
    runtime: Runtime = Depends(get_runtime),
) -> ActionCounts:
    runtime.guard.expire_overdue()
    rows = runtime.store.query(
        "SELECT status, COUNT(*) AS n FROM pending_actions WHERE created_at >= ? GROUP BY status",
        (since if since is not None else float("-inf"),),
    )
    counts = {row["status"]: row["n"] for row in rows}
    by_status = {status: counts.get(status, 0) for status in ACTION_STATUSES}
    return ActionCounts(since=since, total=sum(counts.values()), **by_status)


# Outcomes that are someone's decision; "expired" is the clock's, not a person's.
DECISIONS = ("executed", "failed", "cancelled")


def _decisions(runtime: Runtime, ids: list[str]) -> dict[str, tuple[str | None, str | None, float]]:
    """Who confirmed or cancelled each action, and on which channel, from the audit log."""
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = runtime.store.query(
        f"SELECT action_id, actor, channel, at FROM audit_log WHERE action_id IN ({marks}) "
        f"AND outcome IN ({','.join('?' for _ in DECISIONS)}) ORDER BY id",
        (*ids, *DECISIONS),
    )
    return {
        row["action_id"]: (*split_actor(row["actor"], row["channel"]), row["at"]) for row in rows
    }


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
    http = settings.channels.http
    return [
        ChannelView(
            name="http",
            enabled=True,
            detail={"host": runtime.host, "port": runtime.port, "public_url": runtime.public_url},
            address=ServerAddress(
                host=runtime.host,
                port=runtime.port,
                configured_host=http.host,
                configured_port=http.port,
                public_url=runtime.public_url,
                url=runtime.base_url(),
            ),
        ),
        ChannelView(
            name="web",
            enabled=True,
            detail={
                "stt": getattr(runtime.stt, "name", None),
                "tts": getattr(runtime.tts, "name", None),
            },
        ),
        ChannelView(
            name="telegram",
            enabled=settings.channels.telegram.enabled,
            detail={
                **telegram,
                "token_env": settings.channels.telegram.token_env,
                "token_present": bool(os.environ.get(settings.channels.telegram.token_env)),
                "voice_replies": settings.channels.telegram.voice_replies,
            },
        ),
    ]


def bot_link(username: str | None) -> str | None:
    return f"https://t.me/{username}" if username else None


@router.get("/telegram", response_model=TelegramView, summary="The Telegram bot and paired chats")
async def telegram(
    _: Principal = Depends(reader), runtime: Runtime = Depends(get_runtime)
) -> TelegramView:
    from ira.channels.telegram import PAIRING_SECONDS, bot_identity, paired_chats

    cfg = runtime.settings.channels.telegram
    bot = await bot_identity(runtime)
    state = runtime.channel_state.get("telegram", {})
    return TelegramView(
        enabled=cfg.enabled,
        token_env=cfg.token_env,
        token_present=bool(os.environ.get(cfg.token_env)),
        bot_username=bot.get("username"),
        bot_link=bot_link(bot.get("username")),
        bot_error=bot.get("error"),
        running=bool(state.get("running")),
        last_poll_at=state.get("last_poll_at"),
        last_error=state.get("last_error"),
        pairing_seconds=PAIRING_SECONDS,
        chats=[TelegramChat(**row) for row in paired_chats(runtime.store)],
    )


@router.get(
    "/audit",
    response_model=list[AuditRow],
    summary="Action audit log, newest first",
    responses=PAGED,
)
def audit(
    response: Response,
    limit: int = Query(100, ge=1, le=1000),
    before_id: int | None = Query(None, description="Page: only rows older than this id."),
    _: Principal = Depends(reader),
    runtime: Runtime = Depends(get_runtime),
) -> list[AuditRow]:
    out = []
    for row in page(runtime.guard.audit(limit + 1, before_id), limit, response):
        row["actor"], row["channel"] = split_actor(row["actor"], row["channel"])
        out.append(AuditRow(**row))
    return out


@router.get("/users", response_model=list[AdminUserRow], summary="Accounts (no password hashes)")
def users(
    _: Principal = Depends(reader), runtime: Runtime = Depends(get_runtime)
) -> list[AdminUserRow]:
    return [AdminUserRow(**u.public(), has_pin=u.has_pin) for u in runtime.accounts.users()]


@router.get("/roles", response_model=list[RoleView], summary="What each role may do")
def roles(_: Principal = Depends(reader)) -> list[RoleView]:
    return [
        RoleView(role=r, permissions=sorted(PERMISSIONS[r]), description=ROLE_DESCRIPTIONS[r])
        for r in ROLES
    ]


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


@router.get(
    "/sessions",
    response_model=list[AdminSessionRow],
    summary="Every user's signed-in sessions (owner only; no session tokens)",
    responses=PAGED,
)
def sessions(
    response: Response,
    limit: int = Query(100, ge=1, le=500),
    before: float | None = Query(None, description=SESSIONS_BEFORE),
    before_id: str | None = Query(None, description=SESSIONS_BEFORE_ID),
    principal: Principal = Depends(require("users")),
    runtime: Runtime = Depends(get_runtime),
) -> list[AdminSessionRow]:
    rows = runtime.accounts.sessions(limit=limit + 1, before=before, before_id=before_id)
    return [AdminSessionRow(**current_flag(row, principal)) for row in page(rows, limit, response)]


@router.get("/tokens", response_model=list[TokenRow], summary="API tokens (no token values)")
def tokens(
    _: Principal = Depends(reader), runtime: Runtime = Depends(get_runtime)
) -> list[TokenRow]:
    return [TokenRow(**t) for t in runtime.accounts.tokens()]


# Models, keys and settings.


def _auth_mode(cfg: Any) -> str:
    if cfg.type == "fake":
        return "none"
    if cfg.auth != "auto":
        return cfg.auth
    if cfg.type == "anthropic":
        return "x-api-key"
    if cfg.type == "bedrock_mantle":
        return "bearer" if cfg.api_key_env else "sigv4"
    return "bearer" if cfg.api_key_env else "none"


@router.get("/models", response_model=ModelsView, summary="Fallback chains and provider status")
def models(_: Principal = Depends(reader), runtime: Runtime = Depends(get_runtime)) -> ModelsView:
    settings = runtime.settings
    tiers = [
        TierView(
            name=name,
            configured=list(refs),
            chain=list(runtime.gateway.tiers.get(name, refs)),
            overridden=overrides.tier_override(runtime, name) is not None,
            used_by_assistant=name == runtime.assistant.tier,
        )
        for name, refs in settings.models.tiers.items()
    ]
    providers = []
    for name, cfg in settings.models.providers.items():
        prefix = (len(name) + 1, f"{name}:")
        last_ok = runtime.store.one(
            "SELECT MAX(at) AS at FROM calls WHERE ok = 1 AND substr(model, 1, ?) = ?", prefix
        )
        last_error = runtime.store.one(
            "SELECT at, error_kind FROM calls WHERE ok = 0 AND substr(model, 1, ?) = ? "
            "ORDER BY id DESC LIMIT 1",
            prefix,
        )
        providers.append(
            ProviderView(
                name=name,
                type=cfg.type,
                in_use=name in runtime.gateway.providers,
                auth=_auth_mode(cfg),
                key_env=cfg.api_key_env,
                key_present=bool(os.environ.get(cfg.api_key_env)) if cfg.api_key_env else None,
                last_ok_at=last_ok["at"] if last_ok else None,
                last_error_at=last_error["at"] if last_error else None,
                last_error_kind=last_error["error_kind"] if last_error else None,
            )
        )
    return ModelsView(
        tiers=tiers,
        providers=providers,
        cooling=runtime.gateway.cooling(),
        cooling_reasons=runtime.gateway.cooling_reasons(),
        voices=[
            VoiceOption(id=v.id, languages=list(v.languages), gender=v.gender)
            for v in voices_for(getattr(runtime.tts, "name", None))
        ],
    )


@router.get(
    "/keys",
    response_model=list[KeyView],
    summary="Which secret variables are set (never their values)",
)
def keys(_: Principal = Depends(reader), runtime: Runtime = Depends(get_runtime)) -> list[KeyView]:
    used: dict[str, list[str]] = {}
    for name, cfg in runtime.settings.models.providers.items():
        if cfg.api_key_env:
            used.setdefault(cfg.api_key_env, []).append(f"provider {name}")
    telegram = runtime.settings.channels.telegram
    if telegram.enabled:
        used.setdefault(telegram.token_env, []).append("telegram")
    return [
        KeyView(env=env, used_by=who, present=bool(os.environ.get(env)))
        for env, who in sorted(used.items())
    ]


def settings_view(runtime: Runtime) -> SettingsView:
    tts_on = hasattr(runtime.tts, "voice")
    return SettingsView(
        name=SettingValue(
            value=runtime.assistant.name,
            default=runtime.settings.assistant.name,
            overridden=overrides.name_overridden(runtime),
        ),
        voice=SettingValue(
            value=overrides.current_voice(runtime),
            default=overrides.default_voice(runtime) if tts_on else None,
            overridden=overrides.voice_overridden(runtime),
            editable=tts_on,
        ),
        business=runtime.settings.assistant.business,
        tier=runtime.assistant.tier,
        stt=getattr(runtime.stt, "name", None),
        tts=getattr(runtime.tts, "name", None),
    )


@router.get("/settings", response_model=SettingsView, summary="Assistant name and voice")
def settings(
    _: Principal = Depends(reader), runtime: Runtime = Depends(get_runtime)
) -> SettingsView:
    return settings_view(runtime)


# History.


@router.get(
    "/changes",
    response_model=list[ChangeRow],
    summary="Console changes, newest first",
    responses=PAGED,
)
def change_log(
    response: Response,
    limit: int = Query(100, ge=1, le=1000),
    before_id: int | None = Query(None, description="Page: only changes older than this id."),
    _: Principal = Depends(reader),
    runtime: Runtime = Depends(get_runtime),
) -> list[ChangeRow]:
    rows = changes.recent(runtime.store, limit + 1, before_id)
    return [ChangeRow(**row) for row in page(rows, limit, response)]


@router.get("/costs", response_model=list[CostDay], summary="Calls and cost per day")
def costs(
    days: int = Query(30, ge=1, le=366),
    _: Principal = Depends(reader),
    runtime: Runtime = Depends(get_runtime),
) -> list[CostDay]:
    first = dt.date.today() - dt.timedelta(days=days - 1)
    since = dt.datetime.combine(first, dt.time()).timestamp()
    rows = runtime.store.query(
        "SELECT date(at, 'unixepoch', 'localtime') AS day, COUNT(*) AS calls, "
        "SUM(1 - ok) AS failures, COALESCE(SUM(cost_usd), 0) AS cost_usd, "
        "SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens "
        "FROM calls WHERE at >= ? GROUP BY day ORDER BY day DESC",
        (since,),
    )
    return [CostDay(**{**dict(r), "cost_usd": round(r["cost_usd"], 6)}) for r in rows]


@router.get("/security", response_model=SecurityView, summary="PIN lock, sessions and rules")
def security(
    _: Principal = Depends(reader), runtime: Runtime = Depends(get_runtime)
) -> SecurityView:
    guard = runtime.guard
    locked = guard.locked_until()
    action_tools = [t.name for t in runtime.registry if t.kind == "action"]
    return SecurityView(
        locked_seconds=None if locked is None else max(0, round(locked - guard.clock())),
        locked_until=locked,
        wrong_pins=guard.wrong_pins(),
        max_wrong_pins=guard.max_wrong_pins,
        lock_minutes=round(guard.lock_seconds / 60, 1),
        expiry_seconds=guard.expiry_seconds,
        session_days=COOKIE_DAYS,
        cookie_samesite=COOKIE_SAMESITE,
        token_scopes=list(TOKEN_SCOPES),
        users_without_pin=[
            u.email
            for u in runtime.accounts.users()
            if "actions" in u.permissions and not u.has_pin
        ],
        confirm_roles=list(guard.confirm_roles),
        action_rules=[
            ActionRule(tool=name, confirm_roles=list(guard.confirm_roles_for(name)))
            for name in action_tools
        ],
    )
