# Security

IRA sits between a language model and a business's real data, so its design
assumes the model can be wrong, confused or manipulated, and makes sure that
on its own it can never change anything.

## What is protected, and how

### Actions need a human

- An action tool call only creates a **pending action**: validated
  parameters, a summary written by your code, and a 120-second expiry.
- It runs only after `POST /v1/actions/{id}/confirm` (or a typed PIN on
  Telegram) with the confirming person's own **PIN**, and only if their role
  may confirm that action (`actions.confirm_roles`, narrowed per tool).
- Each PIN is stored as a salted PBKDF2-SHA256 hash (600,000 iterations by
  default) and checked off the event loop. Setting one over the API needs
  the account password again.
- **Three wrong PINs lock every action for 15 minutes**, including attempts
  with the right PIN during the lock.
- A compare-and-set on the action's status means it **runs at most once**,
  even when two confirmations race.
- Once it has run, the model sees what became of it (its result, its
  error, a no, or its expiry), never "waiting for confirmation" again, and
  carries on from there. The yes or the PIN itself never passes through a
  model: the server runs the action first, then tells the model.
- Every proposal and outcome is written to `audit_log` with who and which
  channel.

### Tiers, and reading is not doing

- Each tool's tier is in code: 0 reads, 1 small and undoable, 2 needs a
  "yes" from the person who asked, 3 needs a PIN. The model cannot lower it.
- Text written by others (web results, a device's output, a tool marked
  `untrusted`) reaches the model wrapped as data, with a rule that it is
  never instructions. A turn that has read any of it cannot propose a Tier 2
  or 3 action; the call is refused and logged as `refused`.
- A "yes" to a Tier 2 proposal never goes to a model: the assistant matches a
  short yes or no ("haan", "theek hai", "nahi") itself, only from the person
  who asked, in the same conversation, within 120 seconds.
- "What Ira did" logs every tool call without its arguments or result.
- One person's turns may call one tool at most 30 times a minute
  (`assistant.tool_calls_per_minute`), so a model stuck in a loop stops;
  web search has its own 30 an hour, and devices their call limits.
- A device's output is the person's own: an admin reading their conversation
  sees a placeholder, and the parameters of an action on their device are
  hidden from everyone else.

### Devices

- A device pairs with a one-time code (8 characters, 10 minutes, hashed)
  and the person's PIN, and gets its own `irad_` token, hashed on the
  server. It opens the device WebSocket and may talk to Ira for its person
  (ask, voice, confirm an action with the PIN), never change settings, pair
  or manage anything. Revoking it closes the connection and stops it
  everywhere at once; removing an account revokes its devices.
- A device's tools reach only its owner's conversations, and only while the
  skill is on. Switching one on needs the owner's PIN; an admin can only
  switch skills off.
- Frames are capped at 1 MB, calls at 25 seconds and 4 in flight, tools at
  30, events at one per 30 seconds; event text is stripped of markup.
- A `?token=` in a WebSocket address is masked in every log line IRA writes.
- Ira for Mac keeps its token in the Keychain (never in a file, a log or a
  command line) and logs no contents. Its file tools refuse `~/Library`,
  hidden files and key files; its browser tools read titles and addresses
  only; its screen tool sends text, never a picture, and never reads
  password managers or System Settings; its scripts take the model's words
  only as arguments. Each tool answers within its own deadline, under the
  server's 25 seconds.

### The PIN never reaches a model

- The assistant refuses to forward a message that is only 4-12 digits, on
  every channel.
- The Telegram bot deletes such a message with `deleteMessage` before doing
  anything else, and refuses PINs spoken in voice notes.
- The web page sends the PIN only to the confirm endpoint.

### Accounts and credentials

- Passwords: Argon2id (`argon2-cffi`), at least 10 characters. Unknown emails
  take as long to reject as wrong passwords.
- Sign-in throttling: 5 failures per email or client address in 15 minutes
  blocks further tries for 15 minutes.
- Sessions: random 256-bit tokens, stored as SHA-256 hashes, 14-day expiry,
  revocable at logout. In browsers they live in an HTTP-only,
  SameSite=Strict cookie, marked Secure over HTTPS. Each user can list and
  end their own sessions, or all but the current one; the owner can end
  anyone's. Lists show a separate session id, never the token or its hash.
- IRA stores no client IP addresses: not with sessions, not in the audit
  or change logs, nowhere in its database. A session keeps the browser's
  `User-Agent` (cut to 200 characters) so people can tell their devices
  apart, and the server reads a short label such as "Chrome on macOS" from
  it. This is a privacy choice: an address says where someone was, which a
  list of sessions does not need. Sign-in throttling counts recent failures
  per address in memory only; they stop counting after 15 minutes and a
  restart forgets them. The web server's access log, which `ira serve`
  prints to the console, does show each request's address; whatever runs the
  server (systemd, Docker) decides whether that output is kept.
- CSRF: cookie-authenticated requests that change state must carry
  `X-Ira-Request: 1`, a header a cross-site page cannot add without a CORS
  preflight that IRA never allows. They are also refused when `Origin` names
  another host or `Sec-Fetch-Site` is not `same-origin`.
- API tokens: random, stored hashed, owned by a user, scoped, revocable. A
  token can never hold user-management or settings rights, and every write
  under `/v1/admin` refuses tokens outright: it needs a signed-in session.
- Console changes (users, invitations, sessions, tokens, tools, model
  chains, settings) are written to a change log with who, what, when, and the value
  before and after. Secrets never appear in it.
- Invitations: one-time links whose token is stored as a SHA-256 hash and
  expires after 72 hours. The token travels in the URL fragment, which
  browsers do not send to servers. The last owner can never be removed or
  demoted.
- Roles are checked on every route; conversation ids are namespaced by user.
- Telegram pairing codes are one-time, expire after 10 minutes and are
  stored as SHA-256 hashes; the change log records that a pairing started,
  never the code. Pairing a chat as another user needs the owner's `users`
  permission.
- Setup: the first-owner endpoint needs a one-time code printed by
  `ira serve`, throttles wrong codes per address, creates the owner inside a
  write transaction so two racing requests cannot both succeed, and closes
  for good once a user exists.

### Secrets

- `ira.yaml` never contains a key, only the *name* of the environment
  variable that holds it.
- Keys are never stored in the database. The admin API shows only whether
  each named variable is set (`GET /v1/admin/keys`), never its value.
- Errors from model, voice and Telegram calls are scrubbed of the credential
  before they are raised or logged (some servers echo keys back, and the
  Telegram token is part of every URL).
- The `calls` table records model, timing, tokens and cost, never a key or a
  prompt.
- On AWS, prefer an instance or task role: SigV4 signing uses botocore's
  default credential chain, so no key needs to exist on disk.

### The web page

- A strict Content-Security-Policy (`script-src 'self'`, no inline script),
  `X-Frame-Options: DENY`, `nosniff`, `no-referrer`.
- Answers are inserted as text, never as HTML.
- The service worker never caches `/v1`.
- API responses are `Cache-Control: no-store`.

## What it does not do (yet)

- **No TLS of its own.** Put a reverse proxy with HTTPS in front of any
  non-local deployment ([Deployment](deployment.md)).
- **Conversations are stored in plain SQLite.** Protect the data folder and
  its backups like any customer database; retention settings are planned.
- **Prompt injection through tool results is not filtered.** If a tool
  returns text written by outsiders (emails, reviews), the model may follow
  instructions in it. The PIN still stands between it and any change.

## Keeping secrets out of the repository

The repository is public from its first commit:

- `.gitignore` excludes `.env*` (except `.env.example`), `*.db`,
  `*.sqlite*`, `data/`, `logs/`, keys, virtualenvs and build output.
- `pre-commit` runs `detect-secrets` against a reviewed baseline, a
  private-key detector, ruff, and two local hooks:
  - `scripts/check_denylist.py` blocks a commit when a staged file contains
    any entry of a **private deny-list kept outside the repository**
    (`$IRA_DENYLIST`, default `~/.config/ira/denylist.txt`). Entries are
    literals or `re:` regexes, matched case-insensitively. Reports show
    `file:line` and a masked preview, never the full match. A missing list is
    a warning, not an error.
  - `scripts/check_identity.py` blocks a commit whose author or committer
    email is not a GitHub no-reply address, or matches the deny-list.
- CI runs ruff, pytest on Python 3.11 and 3.12, and **gitleaks** over the
  full history on every push. CI has no cloud, chat or model credentials, and
  every test uses fakes.

To report a vulnerability, see `SECURITY.md` in the repository root.
