"""Learning over HTTP: a person's own settings, networks, phone token, observations, reminders.

Switching learning or a source on is a new grant, so it needs the person's
PIN; switching off never does. Everything here is the caller's own: nobody,
an owner included, reads another person's observations or learnings.

``POST /v1/observations`` takes a phone's place event (an iOS Shortcut),
with a token whose only scope is ``observe``.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ira import changes
from ira.accounts import Principal
from ira.channels.deps import get_runtime, require, require_session
from ira.channels.schemas import (
    ERRORS,
    FeedbackIn,
    FeedbackKept,
    LearningEdit,
    LearningForgotten,
    LearningItem,
    LearningSource,
    LearningUpdate,
    LearningView,
    MacRoutine,
    NetworkName,
    NetworkView,
    ObservationIn,
    ObservationOut,
    ObservationRow,
    OkResponse,
    PhoneToken,
    PhoneTokenCreated,
    PinOnly,
    ReminderView,
)
from ira.learning.learner import Learner
from ira.learning.service import LearningService
from ira.learning.store import LearningError
from ira.runtime import Runtime
from ira.usersettings import LEARNING_SOURCES

router = APIRouter(tags=["learning"], responses=ERRORS)
asker = require("ask")
your_session = require_session("ask")

PIN_STATUS = {"wrong_pin": 403, "locked": 423, "no_pin": 409}
PHONE_TOKEN_LABEL = "iPhone Shortcuts"
SOURCE_WORDS = {
    "phone": "Your phone: an iOS Shortcut tells Ira when you reach or leave a named place.",
    "conversation": 'What you say: "main office nikal raha hoon" is noted, in your own words.',
    "feedback": "Your thumbs up and down on answers: how you like to be answered.",
}


def learning_of(runtime: Runtime) -> LearningService:
    assert runtime.learning is not None
    return runtime.learning


def learner_of(runtime: Runtime) -> Learner:
    assert runtime.learner is not None
    return runtime.learner


async def check_pin(runtime: Runtime, who: Principal, pin: str | None, what: str) -> None:
    if not pin:
        raise HTTPException(403, detail=f"{what} needs your PIN")
    outcome = await runtime.guard.check_pin(
        pin, user_id=who.user.id, what=what, actor=who.actor, channel=who.channel
    )
    if outcome.status != "confirmed":
        raise HTTPException(PIN_STATUS.get(outcome.status, 403), detail=outcome.message)


def phone_tokens(runtime: Runtime, user_id: int) -> list[PhoneToken]:
    rows = runtime.store.query(
        "SELECT id, label, created_at, last_used_at FROM api_tokens "
        "WHERE user_id = ? AND scopes = 'observe' AND revoked_at IS NULL ORDER BY created_at",
        (user_id,),
    )
    return [PhoneToken(**dict(r)) for r in rows]


def learning_view(runtime: Runtime, user_id: int) -> LearningView:
    learning = learning_of(runtime)
    prefs = runtime.assistant.user_settings.get(user_id)
    assert runtime.hub is not None
    counts = Counter(o["kind"] for o in learning.data.observations(user_id))
    return LearningView(
        on=prefs.learning,
        sources=[
            LearningSource(name=name, on=name in prefs.learning_sources, description=text)
            for name, text in SOURCE_WORDS.items()
        ],
        macs=[
            MacRoutine(device_id=d.id, label=d.label, on="routine" in d.skills)
            for d in runtime.hub.devices.for_user(user_id)
            if d.kind in ("mac", "windows")
        ],
        days=prefs.learning_days,
        nudges=prefs.nudges,
        networks=[NetworkView(**n) for n in learning.data.networks(user_id)],
        phone_tokens=phone_tokens(runtime, user_id),
        observations=dict(counts),
        learnings=[LearningItem(**item.public()) for item in learning.data.learnings(user_id)],
        reminders=[ReminderView(**r) for r in learning.data.reminders(user_id)],
    )


@router.get(
    "/v1/me/learning", response_model=LearningView, summary="What Ira may notice, and knows"
)
def my_learning(
    who: Principal = Depends(asker), runtime: Runtime = Depends(get_runtime)
) -> LearningView:
    return learning_view(runtime, who.user.id)


@router.patch(
    "/v1/me/learning",
    response_model=LearningView,
    summary="Switch learning, its sources or nudges (on needs your PIN), and how long to keep",
)
async def update_my_learning(
    body: LearningUpdate,
    who: Principal = Depends(your_session),
    runtime: Runtime = Depends(get_runtime),
) -> LearningView:
    settings = runtime.assistant.user_settings
    prefs = settings.get(who.user.id)
    sent = body.model_fields_set
    sources = prefs.learning_sources
    if "sources" in sent and body.sources is not None:
        unknown = [s for s in body.sources if s not in LEARNING_SOURCES]
        if unknown:
            raise HTTPException(400, detail=f"unknown source(s): {', '.join(unknown)}")
        sources = [s for s in LEARNING_SOURCES if s in body.sources]
    turning_on = []
    if body.on and not prefs.learning:
        turning_on.append("learning")
    turning_on += [s for s in sources if s not in prefs.learning_sources]
    if body.nudges and not prefs.nudges:
        turning_on.append("nudges")
    if turning_on:
        await check_pin(runtime, who, body.pin, f"switching on {', '.join(turning_on)}")
    user_id = who.user.id
    if "on" in sent and body.on is not None:
        settings.set(user_id, "learning", True if body.on else None)
    if "sources" in sent:
        settings.set(user_id, "learning_sources", sources or None)
    if "days" in sent:
        settings.set(user_id, "learning_days", body.days)
        if body.days is not None:
            learning_of(runtime).data.purge(user_id, body.days)
    if "nudges" in sent and body.nudges is not None:
        settings.set(user_id, "nudges", True if body.nudges else None)
    after = settings.get(user_id)
    if (after.learning, after.learning_sources, after.nudges) != (
        prefs.learning,
        prefs.learning_sources,
        prefs.nudges,
    ):
        changes.record(
            runtime.store,
            who.actor,
            "learning.settings",
            who.user.email,
            channel=who.channel,
            before={"on": prefs.learning, "sources": prefs.learning_sources},
            after={"on": after.learning, "sources": after.learning_sources},
        )
    return learning_view(runtime, user_id)


@router.put(
    "/v1/me/networks/{fingerprint}",
    response_model=NetworkView,
    summary="Name a network your Mac or PC reported (by its hash): Office, Home",
)
def name_my_network(
    fingerprint: str,
    body: NetworkName,
    who: Principal = Depends(your_session),
    runtime: Runtime = Depends(get_runtime),
) -> NetworkView:
    data = learning_of(runtime).data
    try:
        named = data.name_network(who.user.id, fingerprint, body.label)
    except LearningError as exc:
        raise HTTPException(400, detail=str(exc)) from None
    if not named:
        raise HTTPException(404, detail="no such network")
    row = next(n for n in data.networks(who.user.id) if n["fingerprint"] == fingerprint)
    return NetworkView(**row)


@router.delete(
    "/v1/me/networks/{fingerprint}", response_model=OkResponse, summary="Forget a network"
)
def forget_my_network(
    fingerprint: str,
    who: Principal = Depends(your_session),
    runtime: Runtime = Depends(get_runtime),
) -> OkResponse:
    if not learning_of(runtime).data.forget_network(who.user.id, fingerprint):
        raise HTTPException(404, detail="no such network")
    return OkResponse()


@router.post(
    "/v1/me/learning/phone-token",
    response_model=PhoneTokenCreated,
    summary="A token for your phone's Shortcuts: it can only report places (needs your PIN)",
)
async def create_phone_token(
    body: PinOnly, who: Principal = Depends(your_session), runtime: Runtime = Depends(get_runtime)
) -> PhoneTokenCreated:
    await check_pin(runtime, who, body.pin, "a phone token for learning")
    token, token_id = runtime.accounts.create_token(who.user, PHONE_TOKEN_LABEL, ["observe"])
    changes.record(
        runtime.store,
        who.actor,
        "token.created",
        token_id,
        channel=who.channel,
        after={"label": PHONE_TOKEN_LABEL, "scopes": ["observe"]},
    )
    return PhoneTokenCreated(id=token_id, token=token, url=f"{runtime.base_url()}/v1/observations")


@router.delete(
    "/v1/me/learning/phone-token/{token_id}",
    response_model=OkResponse,
    summary="Revoke your phone's token",
)
def revoke_phone_token(
    token_id: str, who: Principal = Depends(your_session), runtime: Runtime = Depends(get_runtime)
) -> OkResponse:
    if token_id not in {t.id for t in phone_tokens(runtime, who.user.id)}:
        raise HTTPException(404, detail="no such token")
    runtime.accounts.revoke_token_id(token_id)
    changes.record(runtime.store, who.actor, "token.revoked", token_id, channel=who.channel)
    return OkResponse()


@router.post(
    "/v1/observations",
    response_model=ObservationOut,
    summary="A phone reports reaching or leaving a named place (a token with scope observe)",
)
async def observe(
    body: ObservationIn,
    who: Principal = Depends(require("observe")),
    runtime: Runtime = Depends(get_runtime),
) -> ObservationOut:
    try:
        kept = await learning_of(runtime).from_phone(who.user.id, body.event, body.place)
    except LearningError as exc:
        raise HTTPException(400, detail=str(exc)) from None
    return ObservationOut(recorded=kept is not None)


@router.get(
    "/v1/me/observations",
    response_model=list[ObservationRow],
    summary="Your own observations, oldest first (for the evidence plots)",
)
def my_observations(
    days: int = Query(30, ge=1, le=365),
    kind: str | None = Query(None),
    who: Principal = Depends(asker),
    runtime: Runtime = Depends(get_runtime),
) -> list[ObservationRow]:
    learning = learning_of(runtime)
    since = learning.clock() - days * 86400
    rows = learning.data.observations(who.user.id, since=since, kinds=(kind,) if kind else None)
    return [ObservationRow(**{k: r[k] for k in ObservationRow.model_fields}) for r in rows]


@router.get("/v1/me/reminders", response_model=list[ReminderView], summary="Your open reminders")
def my_reminders(
    who: Principal = Depends(asker), runtime: Runtime = Depends(get_runtime)
) -> list[ReminderView]:
    return [ReminderView(**r) for r in learning_of(runtime).data.reminders(who.user.id)]


@router.delete(
    "/v1/me/reminders/{reminder_id}", response_model=OkResponse, summary="Cancel a reminder"
)
def cancel_my_reminder(
    reminder_id: str,
    who: Principal = Depends(your_session),
    runtime: Runtime = Depends(get_runtime),
) -> OkResponse:
    if not learning_of(runtime).data.cancel_reminder(who.user.id, reminder_id):
        raise HTTPException(404, detail="no such reminder")
    return OkResponse()


# Learnings: what Ira found, and the person's answers.


@router.post(
    "/v1/me/learning/refresh",
    response_model=LearningView,
    summary="Look for patterns now (the learner also runs every night)",
)
async def refresh_my_learning(
    who: Principal = Depends(your_session), runtime: Runtime = Depends(get_runtime)
) -> LearningView:
    await learner_of(runtime).run(who.user.id)
    return learning_view(runtime, who.user.id)


def _answer(runtime: Runtime, who: Principal, learning_id: str, what: str) -> LearningItem:
    learner = learner_of(runtime)
    try:
        if what == "approve":
            learning = learner.approve(who.user.id, learning_id)
        else:
            learning = learner.reject(who.user.id, learning_id)
    except LearningError as exc:
        status = 404 if "no such" in str(exc) else 409
        raise HTTPException(status, detail=str(exc)) from None
    return LearningItem(**learning.public())


@router.post(
    "/v1/me/learnings/{learning_id}/approve",
    response_model=LearningItem,
    summary="Yes: remember this (it goes into your assistant's context)",
)
def approve_learning(
    learning_id: str,
    who: Principal = Depends(your_session),
    runtime: Runtime = Depends(get_runtime),
) -> LearningItem:
    return _answer(runtime, who, learning_id, "approve")


@router.post(
    "/v1/me/learnings/{learning_id}/reject",
    response_model=LearningItem,
    summary="No: do not remember this, and do not ask again",
)
def reject_learning(
    learning_id: str,
    who: Principal = Depends(your_session),
    runtime: Runtime = Depends(get_runtime),
) -> LearningItem:
    return _answer(runtime, who, learning_id, "reject")


@router.patch(
    "/v1/me/learnings/{learning_id}",
    response_model=LearningItem,
    summary="Reword a learning (its numbers must stay those of the evidence)",
)
def edit_learning(
    learning_id: str,
    body: LearningEdit,
    who: Principal = Depends(your_session),
    runtime: Runtime = Depends(get_runtime),
) -> LearningItem:
    try:
        learning = learner_of(runtime).edit(who.user.id, learning_id, body.text)
    except LearningError as exc:
        status = 404 if "no such" in str(exc) else 400
        raise HTTPException(status, detail=str(exc)) from None
    return LearningItem(**learning.public())


@router.delete(
    "/v1/me/learnings/{learning_id}",
    response_model=LearningForgotten,
    summary="Forget a learning and the observations behind it",
)
def forget_learning(
    learning_id: str,
    who: Principal = Depends(your_session),
    runtime: Runtime = Depends(get_runtime),
) -> LearningForgotten:
    try:
        deleted = learner_of(runtime).forget(who.user.id, learning_id)
    except LearningError as exc:
        raise HTTPException(404, detail=str(exc)) from None
    return LearningForgotten(observations=deleted)


# Feedback on an answer: a thumb, and what would be better.


@router.post(
    "/v1/me/feedback",
    response_model=FeedbackKept,
    summary="A thumb up or down on one of Ira's answers to you",
)
async def give_feedback(
    body: FeedbackIn,
    who: Principal = Depends(your_session),
    runtime: Runtime = Depends(get_runtime),
) -> FeedbackKept:
    from ira.language import detect

    row = runtime.store.one(
        "SELECT m.content FROM messages m JOIN conversations c ON c.id = m.conversation_id "
        "WHERE m.id = ? AND m.role = 'assistant' AND c.user_id = ?",
        (body.message_id, who.user.id),
    )
    if row is None:  # someone else's answer is "not found" too
        raise HTTPException(404, detail="no such answer")
    answer = row["content"] or ""
    detail: dict[str, Any] = {
        "rating": body.rating,
        "language": detect(answer),
        "chars": len(answer),
        "message_id": body.message_id,
    }
    if body.note and body.note.strip():
        detail["note"] = " ".join(body.note.split())[:300]
    kept = await learning_of(runtime).record(who.user.id, "feedback", "feedback", detail=detail)
    return FeedbackKept(learned=kept is not None)
