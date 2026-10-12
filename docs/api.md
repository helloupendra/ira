# API

The API is versioned under `/v1`. The OpenAPI document is at
`/v1/openapi.json` and interactive docs at `/v1/docs`.

## Authentication

Send one of:

- `Authorization: Bearer <token>`: an API token (`ira_t_...`) or a session
  token (`ira_s_...`, from login with `use_cookie: false`);
- the `ira_session` cookie set by `POST /v1/auth/login`. Requests that change
  something (any method but `GET`, `HEAD` and `OPTIONS`) must then also send
  `X-Ira-Request: 1`, and are refused when the browser says they came from
  another site (see [Cross-site request forgery](#cross-site-request-forgery)).

A missing or invalid credential gives `401`; a valid one without the needed
permission gives `403`. Every error body is `{"detail": "..."}` (a list of
field errors on `422`).

| Route | Needs |
| --- | --- |
| `GET /healthz`, `GET /v1/auth/status`, `POST /v1/auth/login` | nothing |
| `GET /v1/setup/status`, `POST /v1/setup/owner`, `POST /v1/auth/setup` | nothing (the setup code) |
| `POST /v1/invites/lookup`, `POST /v1/invites/accept` | nothing (the invitation token) |
| `GET /v1/auth/me`, `GET /v1/info`, `POST /v1/auth/logout`, `GET /v1/me/pin` | any credential |
| `PUT /v1/me/pin` | a session with `actions` |
| `POST /v1/ask`, `POST /v1/ask/stream` | `ask` |
| `POST /v1/voice/transcribe`, `POST /v1/voice/speak` | `voice` |
| `POST /v1/actions/{id}/confirm`, `POST /v1/actions/{id}/cancel` | `actions` (and your own PIN to confirm) |
| `GET /v1/admin/*` | `admin.read` (`GET /v1/admin/users/invites`: `users`) |
| `POST`, `PUT`, `PATCH`, `DELETE` under `/v1/admin` | a session with `admin.write`, or `users` for users and invitations |

## Auth

```http
POST /v1/auth/login
{"email": "owner@example.com", "password": "...", "use_cookie": true}
```

Returns the user, their permissions and the session expiry. With
`use_cookie: true` (the default) the session is an HTTP-only, SameSite=Strict
cookie; with `false` the response carries `session_token` instead. Five failed
sign-ins for one email or address within 15 minutes give `429` for 15 minutes.

The first owner is created with the setup code: see
[First-run setup](#first-run-setup).

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

The PIN is the confirming user's own (set with `PUT /v1/me/pin` or
`ira pin set --user`), and their role must be allowed to confirm this action
(`actions.confirm_roles` in `ira.yaml`, narrowed per tool by
`actions.tools.<name>.confirm_roles`).

| Status | HTTP | Meaning |
| --- | --- | --- |
| `executed` | 200 | it ran; `result` holds the tool's return value |
| `failed` | 200 | it ran and failed; `message` says why |
| `wrong_pin` | 403 | `attempts_left` before the lock |
| `not_allowed` | 403 | your role may not confirm this action; no PIN attempt is used |
| `not_found` | 404 | no such action |
| `already_done` | 409 | executed, cancelled, expired or failed before |
| `no_pin` | 409 | you have not set a PIN yet |
| `expired` | 410 | past its 120 seconds |
| `locked` | 423 | too many wrong PINs; `locked_seconds` left |

`POST /v1/actions/{id}/cancel` drops a pending action.

## Admin (read-only)

All need `admin.read` (owner, admin, viewer), from a session or a token.

| Route | Returns |
| --- | --- |
| `GET /v1/admin/overview` | `Overview`: today's calls, failures, cost, tokens, latency p50/p95, per model, actions by status, active conversations, users |
| `GET /v1/admin/calls?limit=&before_id=` | `CallRow[]`: model calls, newest first, paged by id |
| `GET /v1/admin/conversations?limit=&before=` | `ConversationRow[]`: by last activity, with a `preview` of the first question |
| `GET /v1/admin/conversations/{id}` | `MessageRow[]`: messages, with typed `tool_calls` and tool results |
| `GET /v1/admin/actions?status=&limit=` | `ActionRow[]`: proposals with parameters, status, result, `actor` (who proposed) and `decided_by` / `decided_at` (who confirmed or cancelled) |
| `GET /v1/admin/audit?limit=` | `AuditRow[]`: action outcomes and PIN events with actor and channel |
| `GET /v1/admin/changes?limit=&before_id=` | `ChangeRow[]`: the console change log, newest first |
| `GET /v1/admin/costs?days=30` | `CostDay[]`: calls, failures, tokens and cost per day (server local time) |
| `GET /v1/admin/tools` | `ToolDetail[]`: kind, JSON schema, `enabled`, and for actions `confirm_roles` |
| `GET /v1/admin/channels` | `ChannelView[]`: HTTP, web and Telegram status; Telegram says whether its token variable is set |
| `GET /v1/admin/models` | `ModelsView`: each tier's chain as configured and in use, cool-downs, providers with key status and last success or failure |
| `GET /v1/admin/keys` | `KeyView[]`: each secret variable `ira.yaml` names, who uses it, and whether it is set. Never the value |
| `GET /v1/admin/settings` | `SettingsView`: assistant name and voice, each with its `ira.yaml` default and whether it is overridden |
| `GET /v1/admin/security` | `SecurityView`: PIN lock, wrong PINs so far, session length, cookie SameSite, token scopes, users without a PIN, confirm roles per action |
| `GET /v1/admin/users` | `AdminUserRow[]`: accounts with `has_pin` (no password or PIN hashes) |
| `GET /v1/admin/roles` | `RoleView[]`: what each role may do |
| `GET /v1/admin/tokens` | `TokenRow[]`: API tokens (no token values); `scopes` is comma-separated |
| `GET /v1/admin/users/invites` | `InviteView[]`: open invitations. Needs `users` (owner) |

## Console API

The routes the admin console uses to change things. Model names in this
section (`InviteCreated`, `SettingsView`, ...) are the schemas in
`/v1/openapi.json`, where every field is described; operation ids are the
handler names (`create_invite`, `test_tool`, ...).

### Rules for every write

- **A session, never a token.** Every write under `/v1/admin`, and
  `PUT /v1/me/pin`, needs a signed-in session: the cookie, or a session token
  (`ira_s_...`) as a bearer. An API token gets `403` whatever its scopes.
- **A role.** Users and invitations need `users` (owner). Everything else
  needs `admin.write` (owner, admin). Staff and viewers get `403`.
- **CSRF.** With the cookie, send `X-Ira-Request: 1`. See below.
- **The change log.** Every successful change writes one row: who
  (`actor`, e.g. `owner@example.com via web`), what, the target, and the
  value before and after where there is one. Read it at
  `GET /v1/admin/changes`. Secrets (passwords, PINs, tokens, keys) are never
  written to it.

### Cross-site request forgery

A cookie-authenticated request that changes something is refused with `403`
unless all of these hold:

1. it carries `X-Ira-Request: 1`. A page on another site cannot add a custom
   header without a CORS preflight, and IRA never answers one;
2. `Sec-Fetch-Site`, when the browser sends it, is `same-origin` or `none`;
3. `Origin`, when the browser sends it, names this server: the `Host`
   header, or `X-Forwarded-Host` when a proxy rewrites `Host`.

The cookie itself is `HttpOnly` and `SameSite=Strict`. Requests with a bearer
token are not checked, because a browser never adds one on its own.

### First-run setup

While no account has ever been made, the server holds a one-time **setup
code** (three groups of four hex digits) and `ira serve` prints a link:

```text
http://127.0.0.1:8765/admin/setup#code=7F3A-91C2-0B4E
```

When no console is built into `src/ira/web/admin/`, the link is
`http://127.0.0.1:8765/#code=...` instead, and the chat page's setup form
asks for the code. The code rides in the URL fragment, which browsers never
send to the server or a proxy log. Whatever page receives the link reads
`location.hash`, then posts the code:

| Route | Body | Returns |
| --- | --- | --- |
| `GET /v1/setup/status` | | `SetupStatus`: `needs_owner`, `name`, `version` |
| `POST /v1/setup/owner` | `SetupOwnerRequest`: `code`, `email`, `password` (10+ characters) | `SessionResponse`, and the session cookie |

`POST /v1/setup/owner` answers `403` for a wrong code (five wrong codes from
one address give `429` for 15 minutes), `400` for a bad email or password
(the code stays valid), and `409` once any account exists. Creating the owner
and checking that no account exists happen in one write transaction, so two
racing requests cannot both succeed. The code is then dead.
`POST /v1/auth/setup` (body `email`, `password`, `setup_code`) does the same
for older clients.

### Invitations

An owner invites someone; the response carries the token once, and a path
to open on the server:

```http
POST /v1/admin/users/invites
{"email": "desk@example.com", "role": "staff"}
```

```json
{
  "invite": {"id": "inv_3a9c...", "email": "desk@example.com", "role": "staff",
             "created_by": "owner@example.com", "created_at": 1791800000.0,
             "expires_at": 1792059200.0, "state": "pending"},
  "token": "ira_i_...",
  "path": "/admin/invite#token=ira_i_..."
}
```

The link is the server's origin plus `path`, for example
`https://ira.example.com/admin/invite#token=ira_i_...`. The owner sends it
themselves: IRA sends no email. Only the token's SHA-256 hash is stored; it
works once and expires after 72 hours, and a newer invitation for the same
email replaces an open one.

The invitation page reads the token from `location.hash` and uses two public
routes:

| Route | Body | Returns |
| --- | --- | --- |
| `POST /v1/invites/lookup` | `{"token": "ira_i_..."}` | `PublicInvite`: `email`, `role`, `expires_at`; `410` if unknown, used, withdrawn or expired |
| `POST /v1/invites/accept` | `{"token": "ira_i_...", "password": "..."}` | `SessionResponse`, and the session cookie; `410` as above, `400` for a short password |

Inviting the email of a removed account brings that account back, with its
history, the new password and the invited role.

### Your own PIN

| Route | Needs | Body | Returns |
| --- | --- | --- | --- |
| `GET /v1/me/pin` | any credential | | `PinStatus`: `has_pin`, `can_confirm`, `locked_seconds` |
| `PUT /v1/me/pin` | session, `actions` | `PinSetRequest`: `password` (your account password, checked again), `pin` (4-12 digits) | `OkResponse` |

A wrong password gives `403`; five in 15 minutes give `429`. Setting a PIN
here does not lift a wrong-PIN lock; `ira pin set` on the server does. The
outcome is written to the action audit log as `pin_set`.

### Every console write

| Route | Needs | Body | Returns | Change log `what` |
| --- | --- | --- | --- | --- |
| `POST /v1/admin/users/invites` | `users` | `InviteCreateRequest`: `email`, `role` | `InviteCreated` | `user.invited` |
| `DELETE /v1/admin/users/invites/{invite_id}` | `users` | | `OkResponse`; `404` if not open | `user.invite_withdrawn` |
| `PATCH /v1/admin/users/{user_id}` | `users` | `RoleChange`: `role` | `AdminUserRow`; `409` for the last owner | `user.role` (before, after) |
| `DELETE /v1/admin/users/{user_id}` | `users` | | `OkResponse`; `409` for the last owner | `user.removed` |
| `POST /v1/admin/users/{user_id}/reset-pin` | `users` | | `OkResponse` | `user.pin_reset` |
| `POST /v1/admin/tokens` | `admin.write` | `TokenCreateRequest`: `label`, `scopes` | `TokenCreated` (the `token` value, once) | `token.created` |
| `DELETE /v1/admin/tokens/{token_id}` | `admin.write` | | `OkResponse`; `404` if not active | `token.revoked` |
| `PATCH /v1/admin/tools/{name}` | `admin.write` | `ToolSwitch`: `enabled` | `ToolDetail` | `tool.enabled` (before, after) |
| `POST /v1/admin/tools/{name}/test` | `admin.write` | `ToolTestRequest`: `params` | `ToolTestResult`: `ok`, `seconds`, `result` or `error`; `409` for an action tool | `tool.tested` (the params) |
| `POST /v1/admin/models/test` | `admin.write` | `ModelTestRequest`: `ref` (`provider:model` from a tier) | `ModelTestResult`: `ok`, `seconds`, `text` or `error_kind` and `error` | `model.tested` |
| `PUT /v1/admin/models/tiers/{tier}` | `admin.write` | `TierOrderRequest`: `order` (the same models, reordered; `null` resets) | `TierView` | `model.chain` (before, after) |
| `PATCH /v1/admin/settings` | `admin.write` | `SettingsUpdate`: `name`, `voice` (send only what changes; `null` resets to `ira.yaml`) | `SettingsView` | `settings.name`, `settings.voice` |

Setup and accepting an invitation also write `setup.owner` and
`user.joined`.

Notes:

- **Users.** The last owner can never be removed or demoted: make someone
  else owner first. Removing a user disables the account (the row stays, so
  conversations and logs keep their author) and revokes their sessions,
  tokens and paired Telegram chats. Resetting a PIN clears it; the user sets
  a new one with `PUT /v1/me/pin` and cannot confirm actions until then.
- **Tokens** are created for the signed-in user. Scopes are from `ask`,
  `voice`, `actions` and `admin.read`, and cannot exceed the role. Revoking
  is by id.
- **Tools.** A switched-off tool is hidden from the model and from
  `/v1/info`, and a pending action for it fails instead of running. The
  switch is stored in the database and survives restarts. Testing runs a
  read tool with the given parameters, validated like a model's call, with a
  30-second limit; the result is cut at 20,000 characters.
- **Models.** A test sends one fixed short prompt to that model alone, logs
  the call with purpose `test` (it costs what a call costs), and lifts the
  model's cool-down if it answers. A saved order must list exactly the
  models `ira.yaml` gives the tier; if `ira.yaml` later changes the tier, the
  saved order is ignored.
- **Settings.** The name and voice are stored on top of `ira.yaml` and take
  effect at once. The voice is the text-to-speech voice id (Polly, for
  example `Joanna`; OpenAI, for example `alloy`); it cannot be set while
  text-to-speech is off (`SettingValue.editable` is false).
- **Keys** stay in the environment or `.env`. The console can only see
  whether each variable is set.
