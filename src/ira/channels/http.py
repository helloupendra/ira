"""The HTTP API, the web chat at ``/`` and (from v0.2) the admin console at ``/admin``.

OpenAPI is served at ``/v1/openapi.json`` with interactive docs at ``/v1/docs``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import secrets
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from ira import __version__, web
from ira.accounts import Principal
from ira.channels import (
    account,
    admin,
    admin_write,
    approvals,
    businesses,
    connectors,
    devices,
    learning,
    live,
    me,
    my_tokens,
    reports,
)
from ira.channels.account import claim_setup
from ira.channels.deps import (
    SESSION_COOKIE,
    client_ip,
    get_principal,
    get_runtime,
    require,
    session_body,
    set_session_cookie,
)
from ira.channels.paging import HAS_MORE_HEADER, page
from ira.channels.schemas import (
    CONVERSATION_ID,
    ERRORS,
    ActionOutcome,
    ActionView,
    AskRequest,
    AskResponse,
    ConfirmRequest,
    ErrorDetail,
    InfoResponse,
    LoginRequest,
    MessageRow,
    MyConversationRow,
    OkResponse,
    SessionResponse,
    SetupRequest,
    SpeakRequest,
    StatusResponse,
    StreamEvent,
    ToolView,
    TranscribeResponse,
    UserView,
)
from ira.models.base import ProviderError
from ira.runtime import Runtime
from ira.voice.audio import AudioError, check_wav, to_mono16k
from ira.voice.shorten import speakable
from ira.web import STATIC_DIR

log = logging.getLogger("ira.http")

MAX_AUDIO_BYTES = 10 * 1024 * 1024

OUTCOME_STATUS = {
    "executed": 200,
    "failed": 200,
    "cancelled": 200,
    "wrong_pin": 403,
    "not_found": 404,
    "already_done": 409,
    "no_pin": 409,
    "expired": 410,
    "locked": 423,
    "not_allowed": 403,
    "needs_pin": 403,
}

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "media-src 'self' blob:; connect-src 'self'; worker-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


def _conversation_key(principal: Principal, client_id: str) -> str:
    return f"http:{principal.user.id}:{client_id}"


def action_view(runtime: Runtime, principal: Principal, action: dict[str, Any]) -> ActionView:
    """An action as the caller sees it: who may confirm it, and whether the caller can."""
    roles = runtime.guard.confirm_roles_for(action["tool"])
    pending = runtime.guard.get(action["id"])
    tier = action.get("tier", 3)
    return ActionView(
        **action,
        confirm_roles=list(roles),
        can_confirm=principal.can("actions") and principal.user.role in roles,
        can_approve=tier == 2 and pending is not None and pending.user_id == principal.user.id,
    )


# --- auth -------------------------------------------------------------------------

auth = APIRouter(prefix="/v1/auth", tags=["auth"])


@auth.get("/status", response_model=StatusResponse, summary="Public: name and setup state")
def auth_status(runtime: Runtime = Depends(get_runtime)) -> StatusResponse:
    return StatusResponse(
        name=runtime.assistant.name,
        version=__version__,
        setup_required=runtime.accounts.needs_owner(),
    )


@auth.post(
    "/setup",
    response_model=SessionResponse,
    summary="Create the first owner (once); same as POST /v1/setup/owner",
)
def auth_setup(
    body: SetupRequest,
    request: Request,
    response: Response,
    runtime: Runtime = Depends(get_runtime),
) -> SessionResponse:
    return claim_setup(runtime, request, response, body.setup_code, body.email, body.password)


@auth.post("/login", response_model=SessionResponse, summary="Sign in with email and password")
def auth_login(
    body: LoginRequest,
    request: Request,
    response: Response,
    runtime: Runtime = Depends(get_runtime),
) -> SessionResponse:
    limiter = runtime.accounts.limiter
    keys = (f"email:{body.email.strip().lower()}", f"ip:{client_ip(request)}")
    attempt = limiter.take(*keys)  # counted before the check: guesses cannot race the limit
    if attempt is None:
        raise HTTPException(429, detail="too many failed sign-ins; try again in 15 minutes")
    with runtime.accounts.checking:
        user = runtime.accounts.authenticate(body.email, body.password)
    if user is None:
        raise HTTPException(401, detail="wrong email or password")
    limiter.release(attempt, *keys)
    limiter.clear(keys[0])
    token, expires = runtime.accounts.start_session(
        user, user_agent=request.headers.get("user-agent")
    )
    principal = runtime.accounts.session_principal(token)
    assert principal is not None
    if body.use_cookie:
        set_session_cookie(response, request, token, expires)
        return session_body(principal, expires)
    return session_body(principal, expires, token)


@auth.post("/logout", response_model=OkResponse, summary="End this session")
def auth_logout(
    request: Request,
    response: Response,
    principal: Principal = Depends(get_principal),
    runtime: Runtime = Depends(get_runtime),
) -> OkResponse:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    token = token or request.cookies.get(SESSION_COOKIE)
    if principal.via == "session" and token:
        runtime.accounts.end_session(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return OkResponse()


@auth.get("/me", response_model=SessionResponse, summary="Who am I, and what may I do")
def auth_me(principal: Principal = Depends(get_principal)) -> SessionResponse:
    return session_body(principal, None)


# --- end-user API -----------------------------------------------------------------

api = APIRouter(prefix="/v1")


@api.get("/info", response_model=InfoResponse, tags=["ask"], summary="Assistant and caller info")
def info(
    principal: Principal = Depends(get_principal), runtime: Runtime = Depends(get_runtime)
) -> InfoResponse:
    prefs = runtime.assistant.user_settings.get(principal.user.id)
    hindi = prefs.reply_language != "en" and bool({"hi", "hinglish"} & set(prefs.languages))
    return InfoResponse(
        name=runtime.assistant.name_for(principal.user.id),
        version=__version__,
        stt=getattr(runtime.stt, "name", None),
        tts=getattr(runtime.tts, "name", None),
        browser_stt=runtime.settings.voice.browser_stt,
        live=callable(getattr(runtime.stt, "live", None))
        and runtime.tts is not None
        and principal.can("voice")
        and principal.can("ask"),
        mic_language="hi-IN" if hindi else "en-IN",
        tools=[
            ToolView(name=t.name, kind=t.kind, description=t.description)
            for t in runtime.registry
            if runtime.registry.is_enabled(t.name)
        ],
        user=UserView(**principal.user.public()),
        permissions=sorted(principal.permissions),
    )


@api.post("/ask", response_model=AskResponse, tags=["ask"], summary="Ask and wait for the answer")
async def ask(
    body: AskRequest,
    principal: Principal = Depends(require("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> AskResponse:
    client_id = body.conversation_id or secrets.token_hex(6)
    reply = await runtime.assistant.ask(
        body.text,
        conversation_id=_conversation_key(principal, client_id),
        channel=principal.channel,
        actor=principal.actor,
        user_id=principal.user.id,
    )
    data = reply.public()
    data["conversation_id"] = client_id
    if data["action"] is not None:
        data["action"] = action_view(runtime, principal, data["action"])
    return AskResponse(**data)


@api.get(
    "/conversations",
    response_model=list[MyConversationRow],
    tags=["ask"],
    summary="Your recent conversations from the web chat and the API",
    responses={
        **ERRORS,
        200: {"description": "One page, newest first", "headers": HAS_MORE_HEADER},
    },
)
def my_conversations(
    response: Response,
    limit: int = Query(50, ge=1, le=500),
    before: float | None = Query(
        None, description="Page: only conversations active before this (the last row's last_at)."
    ),
    before_id: str | None = Query(
        None,
        description="With before: the last row's id, so conversations that share its last_at "
        "are neither skipped nor repeated. Ignored without before.",
    ),
    principal: Principal = Depends(require("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> list[MyConversationRow]:
    prefix = _conversation_key(principal, "")
    rows = runtime.conversations.recent(
        limit + 1,
        before,
        before_id=None if before_id is None else prefix + before_id,
        user_id=principal.user.id,
        prefix=prefix,
    )
    return [
        MyConversationRow(
            **{k: row[k] for k in MyConversationRow.model_fields if k != "id"},
            id=row["id"][len(prefix) :],
        )
        for row in page(rows, limit, response)
    ]


@api.get(
    "/conversations/{conversation_id}",
    response_model=list[MessageRow],
    tags=["ask"],
    summary="One of your conversations, message by message",
    responses={
        **ERRORS,
        404: {"model": ErrorDetail, "description": "Not one of your conversations"},
    },
)
def my_conversation(
    conversation_id: str,
    principal: Principal = Depends(require("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> list[MessageRow]:
    key = _conversation_key(principal, conversation_id)
    # Someone else's conversation is "not found", so the answer does not say it exists.
    if not re.fullmatch(CONVERSATION_ID, conversation_id) or (
        runtime.conversations.owner(key) != principal.user.id
    ):
        raise HTTPException(404, detail="no such conversation")
    runtime.guard.expire_overdue()
    return [MessageRow(**m) for m in runtime.conversations.transcript(key)]


class EventStream(StreamingResponse):
    media_type = "text/event-stream"


@api.post(
    "/ask/stream",
    tags=["ask"],
    summary="Ask and stream the answer as server-sent events",
    response_class=EventStream,
    responses={
        200: {
            "model": StreamEvent,
            "description": "Server-sent events. Each `data:` line is one JSON object, a "
            "StreamEvent: start, then tool / tool_result / action / delta / error events, "
            "then done.",
            # Each event is an object, although the body as a whole is text.
            "content": {"text/event-stream": {"schema": {"type": "object"}}},
        }
    },
)
async def ask_stream(
    body: AskRequest,
    principal: Principal = Depends(require("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> StreamingResponse:
    client_id = body.conversation_id or secrets.token_hex(6)

    async def events() -> AsyncIterator[str]:
        yield _sse({"type": "start", "conversation_id": client_id})
        async for event in runtime.assistant.events(
            body.text,
            conversation_id=_conversation_key(principal, client_id),
            channel=principal.channel,
            actor=principal.actor,
            user_id=principal.user.id,
        ):
            if event["type"] == "done":
                event = {**event, "conversation_id": client_id}
            elif event["type"] == "action":
                event = {**event, "action": action_view(runtime, principal, event["action"])}
            yield _sse(event)

    return EventStream(events(), headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(event: dict[str, Any]) -> str:
    # Through the typed model, so an event carries exactly its documented fields.
    data = StreamEvent.model_validate(event).model_dump(mode="json")
    return f"data: {json.dumps(data)}\n\n"


@api.post(
    "/voice/transcribe",
    response_model=TranscribeResponse,
    tags=["voice"],
    summary="Speech to text (send a WAV body)",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def transcribe(
    request: Request,
    _: Principal = Depends(require("voice")),
    runtime: Runtime = Depends(get_runtime),
) -> TranscribeResponse:
    if runtime.stt is None:
        raise HTTPException(503, detail="speech-to-text is not configured")
    declared = int(request.headers.get("content-length") or 0)
    if declared > MAX_AUDIO_BYTES:
        raise HTTPException(413, detail="audio is larger than 10 MB")
    data = await request.body()
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, detail="audio is larger than 10 MB")
    try:
        info = check_wav(data, max_seconds=runtime.settings.voice.max_audio_seconds)
        wav = await asyncio.to_thread(to_mono16k, data)
    except AudioError as exc:
        raise HTTPException(415, detail=str(exc)) from None
    try:
        text = await runtime.stt.transcribe(wav)
    except ProviderError as exc:
        log.warning("transcription failed: %s", exc)
        raise HTTPException(502, detail="transcription failed") from None
    return TranscribeResponse(text=text, seconds=round(info.seconds, 2))


@api.post(
    "/voice/speak",
    tags=["voice"],
    summary="Text to speech (returns MP3)",
    response_class=Response,
    responses={200: {"content": {"audio/mpeg": {}}}},
)
async def speak(
    body: SpeakRequest,
    _: Principal = Depends(require("voice")),
    runtime: Runtime = Depends(get_runtime),
) -> Response:
    if runtime.tts is None:
        raise HTTPException(503, detail="text-to-speech is not configured")
    text = (
        speakable(body.text, runtime.settings.voice.max_spoken_chars) if body.shorten else body.text
    )
    if not text:
        raise HTTPException(400, detail="nothing to say")
    try:
        audio = await runtime.tts.speak(text)
    except ProviderError as exc:
        log.warning("speech synthesis failed: %s", exc)
        raise HTTPException(502, detail="speech synthesis failed") from None
    return Response(content=audio, media_type="audio/mpeg")


def _outcome_response(
    response: Response,
    outcome: Any,
    runtime: Runtime,
    principal: Principal,
    after: dict[str, Any] | None = None,
) -> ActionOutcome:
    response.status_code = OUTCOME_STATUS.get(outcome.status, 200)
    body = outcome.public()
    if "action" in body:
        body["action"] = action_view(runtime, principal, body["action"])
    if after and after.get("in_call"):
        body["continued_in_call"] = True
    elif after:
        body["reply"] = after.get("text") or None
        body["reply_message_id"] = after.get("message_id")
    return ActionOutcome(**body)


@api.post(
    "/actions/{action_id}/confirm",
    response_model=ActionOutcome,
    tags=["actions"],
    summary="Run a proposed action after checking the PIN",
)
async def confirm_action(
    action_id: str,
    body: ConfirmRequest,
    response: Response,
    principal: Principal = Depends(require("actions")),
    runtime: Runtime = Depends(get_runtime),
) -> ActionOutcome:
    signed = (body.device_id, body.signature) if body.signature and body.device_id else None
    outcome = await runtime.guard.confirm(
        action_id,
        body.pin,
        actor=principal.actor,
        channel=principal.channel,
        user_id=principal.user.id,
        role=principal.user.role,
        signed=signed,
    )
    after = await runtime.continue_after(outcome, actor=principal.actor)
    return _outcome_response(response, outcome, runtime, principal, after)


@api.post(
    "/actions/{action_id}/approve",
    response_model=ActionOutcome,
    tags=["actions"],
    summary="Say yes to a Tier 2 action you asked for (no PIN)",
)
async def approve_action(
    action_id: str,
    response: Response,
    principal: Principal = Depends(require("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> ActionOutcome:
    outcome = await runtime.guard.approve(
        action_id, user_id=principal.user.id, actor=principal.actor, channel=principal.channel
    )
    after = await runtime.continue_after(outcome, actor=principal.actor)
    return _outcome_response(response, outcome, runtime, principal, after)


@api.post(
    "/actions/{action_id}/cancel",
    response_model=ActionOutcome,
    tags=["actions"],
    summary="Drop a proposed action",
)
def cancel_action(
    action_id: str,
    response: Response,
    principal: Principal = Depends(require("actions")),
    runtime: Runtime = Depends(get_runtime),
) -> ActionOutcome:
    outcome = runtime.guard.cancel(action_id, actor=principal.actor, channel=principal.channel)
    return _outcome_response(response, outcome, runtime, principal)


# --- app ---------------------------------------------------------------------------

ADMIN_PLACEHOLDER = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>IRA admin</title>
</head><body><h1>Admin console</h1>
<p>The admin console ships in v0.2. Its API is already here:
<a href="/v1/docs">/v1/docs</a> (see the <code>admin</code> section).</p></body></html>"""


class ConsoleFiles(StaticFiles):
    """The console's files. A path with no file behind it and no file extension is one of the
    console's own routes (``/admin/setup``, ``/admin/invite``), so it gets ``index.html`` and the
    console routes it in the browser. A missing asset still answers 404."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or "." in path.rsplit("/", 1)[-1]:
                raise
            return await super().get_response("index.html", scope)


def create_app(runtime: Runtime, *, start_channels: bool = True) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        code = runtime.ensure_setup_code()
        if code and not runtime.setup_code_shown:
            log.warning(
                "No account exists yet. Open %s to create the owner, or run `ira setup`.",
                runtime.setup_link(code),
            )
        tasks: list[asyncio.Task] = []
        if start_channels and runtime.learner is not None:
            from ira.learning.scheduler import LearningScheduler

            scheduler = LearningScheduler(runtime.learner)
            tasks.append(asyncio.create_task(scheduler.run(), name="ira-learning"))
        if start_channels and runtime.settings.channels.telegram.enabled:
            from ira.channels.telegram import event_notifier, start_telegram

            tasks.append(start_telegram(runtime))
            if runtime.hub is not None:
                runtime.hub.notifiers.append(event_notifier(runtime))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            await runtime.aclose()

    app = FastAPI(
        # Operation ids are the handlers' names (create_invite, test_tool...), which
        # read well in clients generated from /v1/openapi.json.
        generate_unique_id_function=lambda route: route.name,
        title="IRA",
        summary="Hey Ira: a self-hosted voice assistant over your own data and tools.",
        version=__version__,
        openapi_url="/v1/openapi.json",
        docs_url="/v1/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.runtime = runtime

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith("/v1/docs"):
            response.headers.setdefault("Content-Security-Policy", CSP)
            response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith("/v1/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.get("/healthz", tags=["system"], response_model=OkResponse, summary="Liveness")
    def healthz() -> OkResponse:
        return OkResponse()

    app.include_router(auth)
    app.include_router(account.router)
    app.include_router(api)
    app.include_router(admin.router)
    app.include_router(admin_write.router)
    app.include_router(me.router)
    app.include_router(devices.router)
    app.include_router(learning.router)
    app.include_router(live.router)
    app.include_router(connectors.router)
    app.include_router(connectors.callback)
    app.include_router(reports.router)
    app.include_router(businesses.router)
    app.include_router(my_tokens.router)
    app.include_router(approvals.router)
    app.include_router(approvals.keys)
    devices.mask_tokens_in_logs()

    @app.get("/pair", include_in_schema=False)
    def pair_page() -> FileResponse:
        """Where a pairing QR code leads: it shows the code to type on the device."""
        return FileResponse(STATIC_DIR / "pair.html")

    if (web.ADMIN_DIR / "index.html").is_file():
        # The mount below only matches "/admin/...", and the catch-all "/" mount would
        # answer a bare "/admin" with 404 before any slash redirect could apply.
        @app.api_route("/admin", methods=["GET", "HEAD"], include_in_schema=False)
        def admin_slash(request: Request) -> RedirectResponse:
            query = request.url.query
            return RedirectResponse("/admin/" + (f"?{query}" if query else ""), status_code=308)

        app.mount("/admin", ConsoleFiles(directory=web.ADMIN_DIR, html=True), name="admin")
    else:

        @app.get("/admin", include_in_schema=False, response_class=HTMLResponse)
        def admin_placeholder() -> str:
            return ADMIN_PLACEHOLDER

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="web")
    return app
