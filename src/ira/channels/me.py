"""The signed-in person's own assistant: their preferences and "What Ira did".

Everything here is about the caller alone. Nobody, an owner included, reads
another person's preferences or activity through these routes.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ira import changes, toollog
from ira.accounts import Principal
from ira.channels.deps import client_ip, get_runtime, require, require_session
from ira.channels.paging import PAGED, page
from ira.channels.schemas import (
    ERRORS,
    ActivityRow,
    DataDeleted,
    DataDeleteRequest,
    GrantView,
    MySettings,
    MySettingsUpdate,
    OkResponse,
    SettingValue,
    WebSearchState,
)
from ira.devices.store import SKILLS
from ira.runtime import Runtime
from ira.usersettings import (
    DEFAULT_WAKE_PHRASE,
    LANGUAGES,
    MAX_NAME,
    MAX_WAKE_PHRASE,
    REPLY_LANGUAGES,
    SettingsError,
    check_languages,
    check_reply_language,
    clean_name,
    valid_timezone,
)

router = APIRouter(tags=["your assistant"], responses=ERRORS)
PIN_STATUS = {"wrong_pin": 403, "locked": 423, "no_pin": 409}
WEB_SEARCH = "Web and news search: your questions go to the web search provider."


def my_settings(runtime: Runtime, user_id: int) -> MySettings:
    settings = runtime.assistant.user_settings
    prefs = settings.get(user_id)
    overridden = settings.overridden(user_id)
    return MySettings(
        assistant_name=SettingValue(
            value=prefs.assistant_name or runtime.assistant.name,
            default=runtime.assistant.name,
            overridden="assistant_name" in overridden,
        ),
        wake_phrase=SettingValue(
            value=prefs.wake_phrase,
            default=DEFAULT_WAKE_PHRASE,
            overridden="wake_phrase" in overridden,
        ),
        languages=prefs.languages,
        reply_language=prefs.reply_language,
        language_options=list(LANGUAGES),
        reply_language_options=list(REPLY_LANGUAGES),
        web_search=WebSearchState(
            on=prefs.web_search,
            web_ready=runtime.search.web_ready if runtime.search else False,
            news_ready=runtime.search.news_ready if runtime.search else False,
        ),
        timezone=prefs.timezone,
    )


@router.get("/v1/me/settings", response_model=MySettings, summary="Your own assistant's settings")
def get_my_settings(
    principal: Principal = Depends(require("ask")), runtime: Runtime = Depends(get_runtime)
) -> MySettings:
    return my_settings(runtime, principal.user.id)


@router.patch(
    "/v1/me/settings",
    response_model=MySettings,
    summary="Name your assistant, set your wake phrase and languages (null resets)",
)
async def update_my_settings(
    body: MySettingsUpdate,
    principal: Principal = Depends(require_session("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> MySettings:
    settings = runtime.assistant.user_settings
    user_id = principal.user.id
    sent = body.model_fields_set
    try:
        if "assistant_name" in sent:
            name = clean_name(body.assistant_name or "", MAX_NAME)
            settings.set(user_id, "assistant_name", name or None)
        if "wake_phrase" in sent:
            phrase = clean_name(body.wake_phrase or "", MAX_WAKE_PHRASE)
            settings.set(user_id, "wake_phrase", phrase or None)
        if "languages" in sent:
            languages = None if body.languages is None else check_languages(body.languages)
            settings.set(user_id, "languages", languages)
        if "timezone" in sent:
            if body.timezone is not None and not valid_timezone(body.timezone):
                raise SettingsError(f"unknown time zone '{body.timezone}'")
            settings.set(user_id, "timezone", body.timezone)
        if "reply_language" in sent:
            reply = (
                None if body.reply_language is None else check_reply_language(body.reply_language)
            )
            settings.set(user_id, "reply_language", reply)
    except SettingsError as exc:
        raise HTTPException(400, detail=str(exc)) from None
    if "web_search" in sent and body.web_search is not None:
        await switch_web_search(runtime, principal, body.web_search, body.pin)
    return my_settings(runtime, user_id)


async def switch_web_search(runtime: Runtime, who: Principal, on: bool, pin: str | None) -> None:
    settings = runtime.assistant.user_settings
    before = settings.get(who.user.id).web_search
    if on and not before:
        # A new grant (questions leave the server): Tier 3, the person's own PIN.
        if not pin:
            raise HTTPException(403, detail="switching web search on needs your PIN")
        outcome = await runtime.guard.check_pin(
            pin,
            user_id=who.user.id,
            what="switch on web search",
            actor=who.actor,
            channel=who.channel,
        )
        if outcome.status != "confirmed":
            raise HTTPException(PIN_STATUS.get(outcome.status, 403), detail=outcome.message)
    if on != before:
        settings.set(who.user.id, "web_search", True if on else None)
        changes.record(
            runtime.store,
            who.actor,
            "grant.web_search",
            who.user.email,
            channel=who.channel,
            before=before,
            after=on,
        )


@router.get(
    "/v1/me/activity",
    response_model=list[ActivityRow],
    summary="What Ira did for you: each tool it used and each action that ran, no contents",
    responses=PAGED,
)
def my_activity(
    response: Response,
    limit: int = Query(100, ge=1, le=500),
    before_id: int | None = Query(None, description="Page: only rows older than this id."),
    principal: Principal = Depends(require("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> list[ActivityRow]:
    rows = toollog.recent(runtime.store, principal.user.id, limit + 1, before_id)
    return [ActivityRow(**row) for row in page(rows, limit, response)]


# Grants: everything a person allowed Ira to use, each with "turn off" beside it.


def grants(runtime: Runtime, user_id: int | None = None) -> list[GrantView]:
    """Every grant switched on: one person's, or everyone's."""
    assert runtime.hub is not None
    devices = runtime.hub.devices
    found = devices.for_user(user_id) if user_id is not None else devices.everyone()
    out = [
        GrantView(
            id=f"device-{device.id}-{skill}",
            user_id=device.user_id,
            email=device.email,
            kind="device_skill",
            skill=skill,
            description=SKILLS.get(skill, skill),
            device_id=device.id,
            device=device.label,
        )
        for device in found
        for skill in device.skills
    ]
    sql = (
        "SELECT s.user_id, u.email FROM user_settings s JOIN users u ON u.id = s.user_id "
        "WHERE s.key = 'web_search' AND s.value = 'true' AND u.disabled_at IS NULL"
    )
    params: list[Any] = []
    if user_id is not None:
        sql += " AND s.user_id = ?"
        params.append(user_id)
    for row in runtime.store.query(sql + " ORDER BY u.email", params):
        out.append(
            GrantView(
                id=f"web-{row['user_id']}",
                user_id=row["user_id"],
                email=row["email"],
                kind="web_search",
                skill="web",
                description=WEB_SEARCH,
            )
        )
    return out


def revoke_grant(runtime: Runtime, who: Principal, grant_id: str, user_id: int | None) -> None:
    """Switch one grant off. ``user_id`` limits it to that person's own grants."""
    grant = next((g for g in grants(runtime, user_id) if g.id == grant_id), None)
    if grant is None:
        raise HTTPException(404, detail="no such grant")
    if grant.kind == "web_search":
        runtime.assistant.user_settings.set(grant.user_id, "web_search", None)
    else:
        assert runtime.hub is not None and grant.device_id is not None
        device = runtime.hub.devices.get(grant.device_id)
        assert device is not None
        runtime.hub.devices.set_skills(device.id, [s for s in device.skills if s != grant.skill])
        runtime.hub.push_skills_soon(device.id)
    changes.record(
        runtime.store,
        who.actor,
        "grant.revoked",
        grant.id,
        channel=who.channel,
        before={"user": grant.email, "skill": grant.skill, "device": grant.device},
    )


@router.get("/v1/me/grants", response_model=list[GrantView], summary="What you allowed Ira to use")
def my_grants(
    principal: Principal = Depends(require("ask")), runtime: Runtime = Depends(get_runtime)
) -> list[GrantView]:
    return grants(runtime, principal.user.id)


@router.delete(
    "/v1/me/grants/{grant_id}", response_model=OkResponse, summary="Switch one of your grants off"
)
def revoke_my_grant(
    grant_id: str,
    principal: Principal = Depends(require_session("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> OkResponse:
    revoke_grant(runtime, principal, grant_id, principal.user.id)
    return OkResponse()


@router.get(
    "/v1/admin/grants",
    response_model=list[GrantView],
    tags=["admin"],
    summary="Everyone's grants: device skills and web search, each one can be switched off",
)
def all_grants(
    _: Principal = Depends(require_session("admin.write")), runtime: Runtime = Depends(get_runtime)
) -> list[GrantView]:
    return grants(runtime)


@router.delete(
    "/v1/admin/grants/{grant_id}",
    response_model=OkResponse,
    tags=["admin: changes"],
    summary="Switch anyone's grant off (only its owner switches one on)",
)
def revoke_any_grant(
    grant_id: str,
    principal: Principal = Depends(require_session("admin.write")),
    runtime: Runtime = Depends(get_runtime),
) -> OkResponse:
    revoke_grant(runtime, principal, grant_id, None)
    return OkResponse()


# Your data: take a copy, or delete it.


def _rows(runtime: Runtime, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict(row) for row in runtime.store.query(sql, params)]


def export_data(runtime: Runtime, principal: Principal) -> dict[str, Any]:
    """Everything IRA keeps about one person, as they would read it. No hashes, no tokens."""
    assert runtime.hub is not None
    user_id = principal.user.id
    runtime.guard.expire_overdue()
    conversations = []
    for row in _rows(
        runtime,
        "SELECT id, channel, started_at, last_at, turns FROM conversations "
        "WHERE user_id = ? ORDER BY started_at",
        (user_id,),
    ):
        row["messages"] = runtime.conversations.transcript(row["id"])
        conversations.append(row)
    devices = runtime.hub.devices
    return {
        "exported_at": time.time(),
        "user": principal.user.public(),
        "settings": {
            row["key"]: json.loads(row["value"])
            for row in runtime.store.query(
                "SELECT key, value FROM user_settings WHERE user_id = ?", (user_id,)
            )
        },
        "conversations": conversations,
        "actions": _rows(
            runtime,
            "SELECT id, tool, params, summary, conversation_id, channel, created_at, status, "
            "result, finished_at, tier, device_id FROM pending_actions "
            "WHERE user_id = ? OR actor = ? ORDER BY created_at",
            (user_id, principal.user.email),
        ),
        "devices": [
            {
                "id": d.id,
                "kind": d.kind,
                "label": d.label,
                "created_at": d.created_at,
                "last_seen_at": d.last_seen_at,
                "version": d.version,
                "tools": d.tools,
                "skills": d.skills,
            }
            for d in devices.for_user(user_id)
        ],
        "events": devices.events(user_id, 1000),
        "activity": toollog.recent(runtime.store, user_id, 100_000),
        "telegram_chats": _rows(
            runtime,
            "SELECT chat_id, name, paired_at FROM telegram_chats WHERE user_id = ?",
            (user_id,),
        ),
        "api_tokens": _rows(
            runtime,
            "SELECT id, label, scopes, created_at, last_used_at, revoked_at FROM api_tokens "
            "WHERE user_id = ?",
            (user_id,),
        ),
        "sessions": [
            {k: s[k] for k in ("id", "created_at", "last_used_at", "expires_at", "user_agent")}
            for s in runtime.accounts.sessions(user_id)
        ],
        **_learning_export(runtime, user_id),
    }


def _learning_export(runtime: Runtime, user_id: int) -> dict[str, Any]:
    if runtime.learning is None:
        return {}
    data = runtime.learning.data
    return {
        "observations": data.observations(user_id),
        "networks": data.networks(user_id),
        "learnings": [item.public() for item in data.learnings(user_id)],
        "reminders": data.reminders(user_id, open_only=False),
    }


@router.get(
    "/v1/me/export",
    summary="Export my data: a JSON file of your conversations, devices, events and settings",
    response_class=Response,
    responses={200: {"content": {"application/json": {}}}},
)
def export_my_data(
    principal: Principal = Depends(require_session()), runtime: Runtime = Depends(get_runtime)
) -> Response:
    data = export_data(runtime, principal)
    day = dt.date.today().isoformat()
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="ira-my-data-{day}.json"'},
    )


@router.post(
    "/v1/me/data/delete",
    response_model=DataDeleted,
    summary="Delete my data: your conversations, devices, events, activity and settings",
)
async def delete_my_data(
    body: DataDeleteRequest,
    request: Request,
    principal: Principal = Depends(require_session()),
    runtime: Runtime = Depends(get_runtime),
) -> DataDeleted:
    limiter = runtime.accounts.limiter
    key = f"delete-password:{principal.user.id}"
    if limiter.blocked(key, f"ip:{client_ip(request)}"):
        raise HTTPException(429, detail="too many wrong passwords; try again in 15 minutes")
    if not runtime.accounts.check_password(principal.user.id, body.password):
        limiter.fail(key)
        raise HTTPException(403, detail="that is not your password")
    limiter.clear(key)
    assert runtime.hub is not None
    user_id = principal.user.id
    store = runtime.store
    for device in runtime.hub.devices.for_user(user_id):
        await runtime.hub.disconnect(device.id, "its owner deleted their data")
    with store.transaction():
        ids = [
            r["id"]
            for r in store.query("SELECT id FROM conversations WHERE user_id = ?", (user_id,))
        ]
        messages = 0
        for conversation_id in ids:
            messages += store.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
            ).rowcount
        conversations = store.execute(
            "DELETE FROM conversations WHERE user_id = ?", (user_id,)
        ).rowcount
        # Actions on the person's own devices are theirs; a business's actions stay its records.
        store.execute(
            "DELETE FROM pending_actions WHERE user_id = ? AND device_id IS NOT NULL", (user_id,)
        )
        events = store.execute("DELETE FROM device_events WHERE user_id = ?", (user_id,)).rowcount
        activity = store.execute("DELETE FROM tool_log WHERE user_id = ?", (user_id,)).rowcount
        store.execute("DELETE FROM device_pairings WHERE user_id = ?", (user_id,))
        devices = store.execute("DELETE FROM devices WHERE user_id = ?", (user_id,)).rowcount
        settings = store.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,)).rowcount
        learned = runtime.learning.data.delete_user(user_id) if runtime.learning else {}
    deleted = DataDeleted(
        conversations=conversations,
        messages=messages,
        devices=devices,
        events=events,
        activity=activity,
        settings=settings,
        observations=learned.get("observations", 0),
        learnings=learned.get("learnings", 0),
        reminders=learned.get("reminders", 0),
    )
    changes.record(
        store,
        principal.actor,
        "me.data_deleted",
        principal.user.email,
        channel=principal.channel,
        after=deleted.model_dump(),
    )
    return deleted
