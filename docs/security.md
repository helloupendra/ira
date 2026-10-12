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
- Every proposal and outcome is written to `audit_log` with who and which
  channel.

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
