"""The signed-in person's own assistant: their preferences and "What Ira did".

Everything here is about the caller alone. Nobody, an owner included, reads
another person's preferences or activity through these routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ira import toollog
from ira.accounts import Principal
from ira.channels.deps import get_runtime, require, require_session
from ira.channels.paging import PAGED, page
from ira.channels.schemas import ERRORS, ActivityRow, MySettings, MySettingsUpdate, SettingValue
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
)

router = APIRouter(prefix="/v1/me", tags=["your assistant"], responses=ERRORS)


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
    )


@router.get("/settings", response_model=MySettings, summary="Your own assistant's settings")
def get_my_settings(
    principal: Principal = Depends(require("ask")), runtime: Runtime = Depends(get_runtime)
) -> MySettings:
    return my_settings(runtime, principal.user.id)


@router.patch(
    "/settings",
    response_model=MySettings,
    summary="Name your assistant, set your wake phrase and languages (null resets)",
)
def update_my_settings(
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
        if "reply_language" in sent:
            reply = (
                None if body.reply_language is None else check_reply_language(body.reply_language)
            )
            settings.set(user_id, "reply_language", reply)
    except SettingsError as exc:
        raise HTTPException(400, detail=str(exc)) from None
    return my_settings(runtime, user_id)


@router.get(
    "/activity",
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
