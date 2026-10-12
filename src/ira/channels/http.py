"""The HTTP API, the web chat at ``/`` and (from v0.2) the admin console at ``/admin``.

OpenAPI is served at ``/v1/openapi.json`` with interactive docs at ``/v1/docs``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ira import __version__
from ira.accounts import Principal
from ira.channels import account, admin
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
from ira.channels.schemas import (
    ActionOutcome,
    AskRequest,
    AskResponse,
    ConfirmRequest,
    InfoResponse,
    LoginRequest,
    OkResponse,
    SessionResponse,
    SetupRequest,
    SpeakRequest,
    StatusResponse,
    ToolView,
    TranscribeResponse,
    UserView,
)
from ira.models.base import ProviderError
from ira.runtime import Runtime
from ira.voice.audio import AudioError, check_wav, to_mono16k
from ira.voice.shorten import speakable
from ira.web import ADMIN_DIR, STATIC_DIR, setup_page

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
}

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "media-src 'self' blob:; connect-src 'self'; worker-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


def _conversation_key(principal: Principal, client_id: str) -> str:
    return f"http:{principal.user.id}:{client_id}"


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
    if limiter.blocked(*keys):
        raise HTTPException(429, detail="too many failed sign-ins; try again in 15 minutes")
    user = runtime.accounts.authenticate(body.email, body.password)
    if user is None:
        limiter.fail(*keys)
        raise HTTPException(401, detail="wrong email or password")
    limiter.clear(keys[0])
    token, expires = runtime.accounts.start_session(user)
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
    return InfoResponse(
        name=runtime.assistant.name,
        version=__version__,
        stt=getattr(runtime.stt, "name", None),
        tts=getattr(runtime.tts, "name", None),
        tools=[
            ToolView(name=t.name, kind=t.kind, description=t.description) for t in runtime.registry
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
    return AskResponse(**data)


@api.post(
    "/ask/stream",
    tags=["ask"],
    summary="Ask and stream the answer as server-sent events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
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
            yield _sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


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


def _outcome_response(response: Response, outcome) -> ActionOutcome:
    response.status_code = OUTCOME_STATUS.get(outcome.status, 200)
    return ActionOutcome(**outcome.public())


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
    outcome = await runtime.guard.confirm(
        action_id,
        body.pin,
        actor=principal.actor,
        channel=principal.channel,
        user_id=principal.user.id,
        role=principal.user.role,
    )
    return _outcome_response(response, outcome)


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
    return _outcome_response(response, outcome)


# --- app ---------------------------------------------------------------------------

ADMIN_PLACEHOLDER = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>IRA admin</title>
</head><body><h1>Admin console</h1>
<p>The admin console ships in v0.2. Its API is already here:
<a href="/v1/docs">/v1/docs</a> (see the <code>admin</code> section).</p></body></html>"""


def create_app(runtime: Runtime, *, start_channels: bool = True) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        code = runtime.ensure_setup_code()
        if code and not runtime.setup_code_shown:
            log.warning(
                "No account exists yet. Open %s#code=%s to create the owner, or run `ira setup`.",
                setup_page(),
                code,
            )
        tasks: list[asyncio.Task] = []
        if start_channels and runtime.settings.channels.telegram.enabled:
            from ira.channels.telegram import start_telegram

            tasks.append(start_telegram(runtime))
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

    if (ADMIN_DIR / "index.html").is_file():
        app.mount("/admin", StaticFiles(directory=ADMIN_DIR, html=True), name="admin")
    else:

        @app.get("/admin", include_in_schema=False, response_class=HTMLResponse)
        def admin_placeholder() -> str:
            return ADMIN_PLACEHOLDER

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="web")
    return app
