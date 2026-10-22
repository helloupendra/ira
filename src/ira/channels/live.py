"""``/v1/voice/live``: real-time voice over a WebSocket (protocol in docs/realtime.md).

Who may call: the Ira app with its session cookie (from its own origin only),
an app with a session or API token, or a paired device with its device
token, which speaks for the person it is paired to. They need ``ask`` and
``voice``, and the server needs a streaming speech-to-text (Transcribe) and
a text-to-speech.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ira.accounts import Principal
from ira.channels.deps import SESSION_COOKIE, device_principal
from ira.runtime import Runtime
from ira.voice.live import PING_SECONDS, SILENT_SECONDS, LiveCall

log = logging.getLogger("ira.voice.live")

router = APIRouter(tags=["voice"])

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_SILENT = 4408


def _same_origin(websocket: WebSocket, runtime: Runtime) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return True  # not a browser
    hosts = {websocket.headers.get("host", "")}
    hosts.update(h.strip() for h in websocket.headers.get("x-forwarded-host", "").split(","))
    if runtime.public_url:
        hosts.add(urlsplit(runtime.public_url).netloc)
    return urlsplit(origin).netloc.lower() in {h.lower() for h in hosts if h}


def principal_for(websocket: WebSocket, runtime: Runtime) -> Principal | None:
    header = websocket.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    token = token or websocket.query_params.get("token", "")
    if token:
        # A paired device speaks for its person: ask, voice and actions, nothing more.
        return runtime.accounts.principal(token) or device_principal(runtime, token)
    cookie = websocket.cookies.get(SESSION_COOKIE)
    if cookie and _same_origin(websocket, runtime):
        return runtime.accounts.session_principal(cookie)
    return None


def _problem(runtime: Runtime, principal: Principal) -> str | None:
    if not (principal.can("ask") and principal.can("voice")):
        return "your role can't talk to Ira by voice"
    if not callable(getattr(runtime.stt, "live", None)):
        return "this server has no streaming speech-to-text (voice.stt.type: transcribe)"
    if runtime.tts is None:
        return "this server has no text-to-speech (voice.tts)"
    return None


@router.websocket("/v1/voice/live")
async def live_voice(websocket: WebSocket) -> None:
    runtime: Runtime = websocket.app.state.runtime
    principal = principal_for(websocket, runtime)
    if principal is None:
        await websocket.close(code=CLOSE_UNAUTHORIZED)  # before accepting: HTTP 403
        return
    await websocket.accept()
    problem = _problem(runtime, principal)
    if problem:
        await websocket.send_text(json.dumps({"type": "error", "message": problem, "fatal": True}))
        await websocket.close(code=CLOSE_FORBIDDEN)
        return

    from ira.channels.http import _conversation_key, action_view

    call = LiveCall(
        runtime,
        principal,
        websocket.send_text,
        websocket.send_bytes,
        conversation_key=lambda client_id: _conversation_key(principal, client_id),
        action_view=lambda action: action_view(runtime, principal, action),
        close_socket=lambda code: websocket.close(code=code),
        max_spoken_chars=max(runtime.settings.voice.max_spoken_chars, 600),
    )
    pinger = asyncio.ensure_future(_ping(websocket, call))
    started = False
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                if started:
                    await call.on_audio(message["bytes"])
                continue
            text = message.get("text") or ""
            if not started:
                try:
                    first = json.loads(text)
                except ValueError:
                    first = {}
                if not isinstance(first, dict) or first.get("type") != "start":
                    await call.send({"type": "error", "message": "send start first", "fatal": True})
                    break
                await call.start(first)
                started = True
                continue
            if not await call.on_text(text):
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("the live call failed")
    finally:
        pinger.cancel()
        await call.close()
        with contextlib.suppress(Exception):
            await websocket.close()


async def _ping(websocket: WebSocket, call: Any) -> None:
    while True:
        await asyncio.sleep(PING_SECONDS)
        if call.clock() - call.last_heard > SILENT_SECONDS:
            with contextlib.suppress(Exception):
                await websocket.close(code=CLOSE_SILENT)
            return
        with contextlib.suppress(Exception):
            await call.send({"type": "ping"})
