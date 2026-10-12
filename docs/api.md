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
| `GET /v1/me/sessions`, `DELETE /v1/me/sessions/{id}`, `POST /v1/me/sessions/revoke-others` | a session (any role) |
| `POST /v1/ask`, `POST /v1/ask/stream`, `GET /v1/conversations`, `GET /v1/conversations/{id}` | `ask` |
| `POST /v1/voice/transcribe`, `POST /v1/voice/speak` | `voice` |
| `POST /v1/actions/{id}/confirm`, `POST /v1/actions/{id}/cancel` | `actions` (and your own PIN to confirm) |
| `GET /v1/admin/*` | `admin.read` (`GET /v1/admin/users/invites` and `GET /v1/admin/sessions`: `users`) |
| `POST`, `PUT`, `PATCH`, `DELETE` under `/v1/admin` | a session with `admin.write`, or `users` for users, invitations and sessions |

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
  "tool_calls": [
    {"id": "call_1", "name": "find_slots", "arguments": {"day": "2026-10-13"},
     "ok": true, "result": "{\"slots\": [\"14:00\", \"14:30\"]}", "truncated": false}
  ],
  "model": "openai:gpt-4o-mini"
}
```

Omit `conversation_id` to start a new conversation; the response returns the
new id. Conversation ids are private to the user who made them.

`tool_calls` (`AskToolCall[]`) lists each tool the model called, in order:

- `id`: unique within the turn; the model's own call id (the transcript's
  `tool_call_id`), with a suffix such as `-2` if the model repeated one;
- `arguments`: what the model passed, as a JSON object (`{}` when it was not
  valid JSON);
- `ok`: false when the call failed (bad arguments, an unknown or switched-off
  tool, or an error from the tool). Proposing an action is ok;
- `result`: the result the model was given, as text, cut to its first 500
  characters; `truncated` is then true and the text ends with `…`. An error
  reads `{"error": "..."}`.

These are results of the caller's own question, which the model has already
seen. `tools_used` (just the names) stays for v0.1 clients.

When the turn proposed an action, `action` is an `ActionView`:

```json
{"id": "act_1f2e...", "tool": "cancel_appointment",
 "summary": "Cancel appointment #3: Riley Demo on Tuesday 13 October at 15:00",
 "status": "pending", "expires_in": 120,
 "confirm_roles": ["owner", "admin"], "can_confirm": false}
```

`confirm_roles` are the roles that may confirm this action:
`actions.tools.<name>.confirm_roles` in `ira.yaml`, or else
`actions.confirm_roles`. `can_confirm` is for the caller: true when their
credential has the `actions` permission and their role is in
`confirm_roles`. When it is false, a client shows no PIN box ("your role
can't confirm this"). It does not say whether the caller has set a PIN;
`GET /v1/me/pin` does. Confirm and cancel responses carry the same fields.

### Streaming

`POST /v1/ask/stream` takes the same body and answers with server-sent events,
one JSON object per `data:` line. Each is a `StreamEvent` in
`/v1/openapi.json`, told apart by `type`:

| `type` | Fields | Meaning |
| --- | --- | --- |
| `start` | `conversation_id` | the turn began |
| `tool` | `id`, `name`, `arguments` | a tool was called; `arguments` is a JSON object |
| `tool_result` | `id`, `name`, `ok`, `result`, `truncated` | that call (same `id`) finished; `result` is cut at 500 characters, as in `tool_calls` above |
| `action` | `action` | an action was proposed: an `ActionView` with `confirm_roles` and `can_confirm`, as above |
| `delta` | `text` | more answer text |
| `error` | `message` | no model could answer |
| `done` | `text`, `model`, `conversation_id` | the full answer; always last |

A `tool_result` follows its `tool` before the next `tool` starts. When a call
proposes an action, its `action` event comes right after its `tool_result`.

### Your conversations

Any credential with `ask` (a phone token with scope `ask` too) can read back
its user's own conversations from the web chat and the API:

| Route | Returns |
| --- | --- |
| `GET /v1/conversations?limit=&before=&before_id=` | `MyConversationRow[]`: `id`, `channel` (`web` or `api`), `started_at`, `last_at`, `turns`, `preview` (the first question, cut to 120 characters); by last activity, newest first. Page with the last row's `last_at` as `before` and its `id` as `before_id`; `X-Has-More` says whether more follow (see [Paging](#paging)) |
| `GET /v1/conversations/{id}` | `MessageRow[]`: the messages, with tool calls and tool results, as in the admin transcript; `404` if it is not yours |

`id` is the `conversation_id` the client sent to `/v1/ask`: send it again to
continue. Someone else's conversation answers `404`, as an unknown one does,
so the answer does not say whether it exists. Telegram chats and
conversations that record no user (from before accounts) are not listed
here; the admin list has them.

An assistant message carries `model`, the `provider:model` that wrote it
(each tool round can fall back to a different one); it is `null` when no
model answered, on other roles, and on messages stored before this field.

A tool result that proposed an action carries that action as it stands now,
in `action` (`MessageAction`: `id`, `tool`, `summary`, `status`,
`expires_at`). Its `content` keeps what the model was told
(`pending_confirmation`), so read the status from `action`: an expired
proposal says `expired` there. `action` is `null` on every other message,
and on proposals stored before this field that could not be matched to
their action when the database was upgraded.

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
| `already_done` | 409 | executed, cancelled or failed before |
| `no_pin` | 409 | you have not set a PIN yet; the message says to set one in the Ira app's menu or ask an owner to reset it |
| `expired` | 410 | past its 120 seconds, whether or not anything had marked it expired yet |
| `locked` | 423 | too many wrong PINs; `locked_seconds` left, and `locked_until` (epoch seconds) when the lock ends |

`POST /v1/actions/{id}/cancel` drops a pending action. Cancelling one past
its expiry answers `expired` (410) too; nothing changes.

**Expiry is the same everywhere.** A proposal past its `expires_at` is
marked `expired` before any list, count or transcript is read (its
`finished_at` is then its `expires_at`), so it never reads as `pending`:
not in `GET /v1/admin/actions?status=pending`, not in the Overview's
`actions` counts or `GET /v1/admin/actions/counts`, and not in a
transcript's `action`.

## Admin (read-only)

All need `admin.read` (owner, admin, viewer), from a session or a token.

| Route | Returns |
| --- | --- |
| `GET /v1/admin/overview` | `Overview`: today's `questions` (user turns stored since the start of today, every channel), model `calls` (one question can make several), failures, cost, tokens, latency p50/p95, per model, actions by status, active conversations, users. "Today" starts at `since`, the server's local midnight (epoch seconds); `since_iso` is the same moment with the server's offset (`2026-10-12T00:00:00+05:30`) and `timezone` the server's zone: an IANA name (`Asia/Kolkata`) when the system names one, else its offset (`+05:30`) |
| `GET /v1/admin/calls?limit=&before_id=` | `CallRow[]`: model calls, newest first, paged by id. `tried` is the models tried in order, joined by commas with no spaces; `tried_list` has them as a list |
| `GET /v1/admin/conversations?limit=&before=&before_id=` | `ConversationRow[]`: by last activity, with a `preview` of the first question |
| `GET /v1/admin/conversations/{id}` | `MessageRow[]`: messages, with typed `tool_calls` and tool results; `404` if unknown |
| `GET /v1/admin/conversations/{id}/info` | `ConversationRow`: one conversation's header (`channel`, `user_id`, `email`, `started_at`, `last_at`, `turns`, `preview`), as in the list; `404` if unknown |
| `GET /v1/admin/actions?status=&limit=&before=&before_id=` | `ActionRow[]`: proposals with parameters, status, result, `actor` (who proposed) and `decided_by` / `decided_at` (who confirmed or cancelled) |
| `GET /v1/admin/actions/counts?since=` | `ActionCounts`: how many actions stand at each status (`pending`, `executing`, `executed`, `failed`, `cancelled`, `expired`) and `total`, over all time, or proposed at or after `since` (epoch seconds) |
| `GET /v1/admin/audit?limit=&before_id=` | `AuditRow[]`: action outcomes and PIN events with actor and channel, newest first |
| `GET /v1/admin/changes?limit=&before_id=` | `ChangeRow[]`: the console change log, newest first |
| `GET /v1/admin/costs?days=30` | `CostDay[]`: calls, failures, tokens and cost per day (server local time) |
| `GET /v1/admin/tools` | `ToolDetail[]`: `kind` (`read` or `action`), JSON schema, `enabled`, and for actions `confirm_roles` |
| `GET /v1/admin/channels` | `ChannelView[]`: HTTP, web and Telegram status; Telegram says whether its token variable is set. The `http` channel's `address` (`ServerAddress`) has the `host` and `port` that `ira serve` bound (its `--host` and `--port`, else `ira.yaml`), `configured_host` and `configured_port` from `ira.yaml`, `public_url` (`channels.http.public_url` or `IRA_PUBLIC_URL`, else `null`) and `url`, the base URL to open: `public_url` when set, else `http://host:port` |
| `GET /v1/admin/models` | `ModelsView`: each tier's chain as configured and in use, cool-downs, providers with key status and last success or failure |
| `GET /v1/admin/keys` | `KeyView[]`: each secret variable `ira.yaml` names, who uses it, and whether it is set. Never the value |
| `GET /v1/admin/settings` | `SettingsView`: assistant name and voice, each with its `ira.yaml` default and whether it is overridden |
| `GET /v1/admin/security` | `SecurityView`: PIN lock, wrong PINs so far, session length, cookie SameSite, token scopes, users without a PIN, confirm roles per action |
| `GET /v1/admin/users` | `AdminUserRow[]`: accounts with `has_pin` (no password or PIN hashes) |
| `GET /v1/admin/roles` | `RoleView[]`: what each role may do |
| `GET /v1/admin/tokens` | `TokenRow[]`: API tokens (no token values); `scopes` is comma-separated |
| `GET /v1/admin/users/invites` | `InviteView[]`: open invitations. Needs `users` (owner) |
| `GET /v1/admin/sessions?limit=&before=&before_id=` | `AdminSessionRow[]`: every user's active sessions, as in `GET /v1/me/sessions` plus `user_id`, `email` and `role`. Needs `users` (owner) |

**`actor` is the person, `channel` is where.** In `ActionRow`, `AuditRow`
and `ChangeRow`, `actor` is the person's email and `channel` is `web`,
`api`, `telegram` or `cli`; `ActionRow` adds `decided_channel` next to
`decided_by`. Older rows put the channel into the actor
(`owner@example.com via web`); reads drop that ending when it names the
row's channel, and the change log, which had no `channel` column, takes its
channel from it. An actor that is not an email (`owner` from an early CLI)
is returned as stored.

### Paging

The lists stay JSON arrays. Every paged list answers with an
`X-Has-More: true|false` header: the server fetches one row more than
`limit`, so `true` means another page exists and `false` that this page is
the last. The header is on `GET /v1/admin/calls`, `/v1/admin/conversations`,
`/v1/admin/actions`, `/v1/admin/changes`, `/v1/admin/audit`,
`/v1/admin/sessions`, `/v1/me/sessions` and `/v1/conversations`, and is
declared on each in `/v1/openapi.json`.

For the next page, send the cursor the last row gives:

| List | Order | Cursor |
| --- | --- | --- |
| calls, changes, audit | id, newest first | `before_id` = the last row's `id` |
| conversations (admin and yours) | `last_at`, newest first, then `id` | `before` = the last row's `last_at` and `before_id` = its `id` |
| actions | `created_at`, newest first, then `id` | `before` = the last row's `created_at` and `before_id` = its `id` |
| sessions (yours and everyone's) | `last_used_at`, newest first, then `id` | `before` = the last row's `last_used_at` and `before_id` = its `id` |

With `before` and `before_id` together, rows that share the same moment are
neither skipped nor repeated. `before` alone still works as it did (only
strictly older rows) and `before_id` without `before` is ignored on these
lists. Sessions default to 100 a page (`limit` up to 500); a session's
`last_used_at` moves each time it is used, so a long walk through sessions
can see one twice.

IRA answers no cross-origin requests, so it sends no CORS headers. A proxy
that adds CORS for a console on another origin must list `X-Has-More` in
`Access-Control-Expose-Headers`, or the browser hides it.

## Console API

The routes the admin console uses to change things. Model names in this
section (`InviteCreated`, `SettingsView`, ...) are the schemas in
`/v1/openapi.json`, where every field is described; operation ids are the
handler names (`create_invite`, `test_tool`, ...).

### Rules for every write

- **A session, never a token.** Every write under `/v1/admin`,
  `PUT /v1/me/pin` and everything under `/v1/me/sessions` (reads too) need a
  signed-in session: the cookie, or a session token (`ira_s_...`) as a
  bearer. An API token gets `403` whatever its scopes.
- **A role.** Users, invitations and other people's sessions need `users`
  (owner). Your own sessions need no particular role. Everything else needs
  `admin.write` (owner, admin). Staff and viewers get `403`.
- **CSRF.** With the cookie, send `X-Ira-Request: 1`. See below.
- **The change log.** Every successful change writes one row: who
  (`actor`, e.g. `owner@example.com`), where (`channel`, `web`), what, the
  target, and the value before and after where there is one. Read it at
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
asks for the code. With `public_url` set, the link starts with it
(`https://ira.example.com/admin/setup#code=...`). The code rides in the URL fragment, which browsers never
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
`https://ira.example.com/admin/invite#token=ira_i_...`. When `public_url` is
set (`channels.http.public_url` or `IRA_PUBLIC_URL`), the response's `url`
is that whole link; otherwise `url` is `null`. The owner sends it
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
| `GET /v1/me/pin` | any credential | | `PinStatus` (below) |
| `PUT /v1/me/pin` | session, `actions` | `PinSetRequest`: `password` (your account password, checked again), `pin` (4-12 digits) | `OkResponse` |

`PinStatus`:

```json
{"has_pin": true, "can_confirm": true, "pin_set_at": 1791800000.0,
 "locked_seconds": null, "locked_until": null,
 "pin_min_length": 4, "pin_max_length": 12}
```

- `pin_set_at`: when you last set your PIN (epoch seconds); `null` without
  a PIN, and for a PIN set before IRA recorded the moment.
- `locked_until`: when the wrong-PIN lock ends (epoch seconds), next to
  `locked_seconds` (the same moment as seconds from now); both `null` when
  actions are not locked. `GET /v1/admin/security` and every
  `ActionOutcome` carry `locked_until` too.
- `pin_min_length`, `pin_max_length`: the PIN rule, read from the one place
  it lives in the server (`ira.security`). `PinSetRequest` and
  `ConfirmRequest` in `/v1/openapi.json` use the same numbers.

A wrong password gives `403`; five in 15 minutes give `429`. Setting a PIN
here does not lift a wrong-PIN lock; `ira pin set` on the server does. The
outcome is written to the action audit log as `pin_set`.

### Your sessions

Each sign-in is a session. The list shows the active ones (not ended, not
expired), most recently used first, as `SessionView`:

```json
{"id": "ses_9b1c...", "created_at": 1791800000.0, "last_used_at": 1791803600.0,
 "expires_at": 1793009600.0, "current": true,
 "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) Firefox/131.0",
 "device": "Firefox on macOS"}
```

`id` names the session; it is not a credential, and the session token and
its hash never appear. `current` marks the session making the request.
`user_agent` is the browser's `User-Agent` at sign-in, cut to 200
characters, and `null` when none was sent or the session started before IRA
stored it. `device` is a short label the server reads from it: the browser
and the system (`Chrome on macOS`, `Safari on iPhone`, `Samsung Internet on
Android`), a known client (`curl`, `Python (httpx)`), or the name a client
gives itself; `null` without a `user_agent`. IRA keeps no client IP
addresses for sessions.

| Route | Needs | Returns |
| --- | --- | --- |
| `GET /v1/me/sessions?limit=&before=&before_id=` | a session | `SessionView[]`: yours, 100 a page, with `X-Has-More` (see [Paging](#paging)) |
| `DELETE /v1/me/sessions/{id}` | a session | `OkResponse`; `404` if it is not one of your active sessions. Ending the current one also clears the cookie |
| `POST /v1/me/sessions/revoke-others` | a session | `SessionsEnded`: `ended`, how many of your other sessions were signed out; this one stays |
| `GET /v1/admin/sessions?limit=&before=&before_id=` | `users` | `AdminSessionRow[]`: everyone's, with `user_id`, `email` and `role`, paged the same way |
| `DELETE /v1/admin/sessions/{id}` | a session with `users` | `OkResponse`; `404` if not active |

An API token cannot list or end sessions, even its own user's. The writes
follow the rules above (CSRF header with the cookie) and write
`session.revoked` (target: the session id, `before`: `{"user": email}`) or
`session.revoked_others` (target: your email, `after`: `{"ended": n}`) to the
change log. Removing a user also ends their sessions.

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
| `DELETE /v1/admin/sessions/{session_id}` | `users` | | `OkResponse`; `404` if not active | `session.revoked` |
| `DELETE /v1/me/sessions/{session_id}` | a session | | `OkResponse`; `404` if not yours and active | `session.revoked` |
| `POST /v1/me/sessions/revoke-others` | a session | | `SessionsEnded` | `session.revoked_others` (only when one ended) |
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
