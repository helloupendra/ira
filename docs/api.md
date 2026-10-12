# API

The API is versioned under `/v1`. The OpenAPI document is at
`/v1/openapi.json` and interactive docs at `/v1/docs`.

## Authentication

Send one of:

- `Authorization: Bearer <token>`: an API token (`ira_t_...`) or a session
  token (`ira_s_...`, from login with `use_cookie: false`);
- the `ira_session` cookie set by `POST /v1/auth/login`. Requests that change
  something must then also send `X-Ira-Request: 1`, which blocks cross-site
  request forgery.

A missing or invalid credential gives `401`; a valid one without the needed
permission gives `403`.

| Route | Needs |
| --- | --- |
| `GET /healthz`, `GET /v1/auth/status`, `POST /v1/auth/login`, `POST /v1/auth/setup` | nothing |
| `GET /v1/auth/me`, `GET /v1/info`, `POST /v1/auth/logout` | any credential |
| `POST /v1/ask`, `POST /v1/ask/stream` | `ask` |
| `POST /v1/voice/transcribe`, `POST /v1/voice/speak` | `voice` |
| `POST /v1/actions/{id}/confirm`, `POST /v1/actions/{id}/cancel` | `actions` (and the PIN to confirm) |
| `GET /v1/admin/*` | `admin.read` |

## Auth

```http
POST /v1/auth/login
{"email": "owner@example.com", "password": "...", "use_cookie": true}
```

Returns the user, their permissions and the session expiry. With
`use_cookie: true` (the default) the session is an HTTP-only, SameSite=Strict
cookie; with `false` the response carries `session_token` instead. Five failed
sign-ins for one email or address within 15 minutes give `429` for 15 minutes.

`POST /v1/auth/setup` with `email`, `password` and `setup_code` creates the
first owner. It answers `409` once any user exists.

## Ask

```http
POST /v1/ask
{"text": "find slots tomorrow", "conversation_id": "kitchen-tablet"}
```

```json
{
  "text": "Tuesday has 14:00 and 14:30 free.",
  "conversation_id": "kitchen-tablet",
  "action": null,
  "tools_used": ["find_slots"],
  "model": "openai:gpt-4o-mini"
}
```

Omit `conversation_id` to start a new conversation; the response returns the
new id. Conversation ids are private to the user who made them.

When the turn proposed an action, `action` is:

```json
{"id": "act_1f2e...", "tool": "cancel_appointment",
 "summary": "Cancel appointment #3: Riley Demo on Tuesday 13 October at 15:00",
 "status": "pending", "expires_in": 120}
```

### Streaming

`POST /v1/ask/stream` takes the same body and answers with server-sent events,
one JSON object per `data:` line:

| `type` | Fields | Meaning |
| --- | --- | --- |
| `start` | `conversation_id` | the turn began |
| `tool` | `name` | a tool was called |
| `action` | `action` | an action was proposed (as above) |
| `delta` | `text` | more answer text |
| `error` | `message` | no model could answer |
| `done` | `text`, `model`, `conversation_id` | the full answer |

## Voice

`POST /v1/voice/transcribe` takes a WAV body (`Content-Type: audio/wav`, up to
10 MB and `max_audio_seconds`) and returns `{"text": ..., "seconds": ...}`.
Mono 16-bit 16 kHz is ideal; other PCM WAVs are converted. Non-WAV data gives
`415`; no speech-to-text configured gives `503`.

`POST /v1/voice/speak` takes `{"text": ..., "shorten": true}` and returns
`audio/mpeg`. With `shorten`, markdown is stripped and long text is cut at a
sentence.

## Actions

```http
POST /v1/actions/act_1f2e.../confirm
{"pin": "4321"}
```

| Status | HTTP | Meaning |
| --- | --- | --- |
| `executed` | 200 | it ran; `result` holds the tool's return value |
| `failed` | 200 | it ran and failed; `message` says why |
| `wrong_pin` | 403 | `attempts_left` before the lock |
| `not_found` | 404 | no such action |
| `already_done` | 409 | executed, cancelled, expired or failed before |
| `no_pin` | 409 | no PIN has been set |
| `expired` | 410 | past its 120 seconds |
| `locked` | 423 | too many wrong PINs; `locked_seconds` left |

`POST /v1/actions/{id}/cancel` drops a pending action.

## Admin (read-only)

| Route | Returns |
| --- | --- |
| `GET /v1/admin/overview` | today: calls, failures, cost, tokens, latency p50/p95, per model, actions by status, active conversations, users |
| `GET /v1/admin/calls?limit=&before_id=` | model calls, newest first, paged by id |
| `GET /v1/admin/conversations?limit=&before=` | conversations by last activity |
| `GET /v1/admin/conversations/{id}` | messages, including tool calls and results |
| `GET /v1/admin/actions?status=&limit=` | proposals with parameters, status and result |
| `GET /v1/admin/audit?limit=` | action outcomes with actor and channel |
| `GET /v1/admin/tools` | registered tools with kind and JSON schema |
| `GET /v1/admin/channels` | HTTP, web and Telegram status |
| `GET /v1/admin/users` | accounts (no password hashes) |
| `GET /v1/admin/tokens` | API tokens (no token values) |
