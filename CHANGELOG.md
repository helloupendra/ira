# Changelog

## [Unreleased]

- **`ira init <folder>`** makes a new business folder from templates in the
  package: a commented `ira.yaml`, a placeholder `tools.py` (one read tool,
  one action tool), a README and a `.gitignore`. `--provider bedrock` fills
  in Bedrock fallback chains, Voxtral speech-to-text and Polly (Kajal,
  `en-IN`). It refuses a folder that is not empty and never writes a secret.
- **`ira doctor [folder]`** checks one business folder: the config, the data
  folder, the port, each tool module, one tiny call to each model and to
  speech-to-text and text-to-speech, the owner's PIN and `public_url`. It
  exits non-zero on a failure; `--no-models` makes no calls.
- **`deploy/aws/`**: run several businesses on one small EC2 server with
  Bedrock and Polly through the instance role and a Cloudflare tunnel.
  `bootstrap.sh` installs IRA from a git ref and is safe to run again to
  upgrade; the `ira@.service` template runs one hardened, capped instance
  per business; `add-business.sh` adds one; plus example tunnel and IAM
  policy files. The walkthrough is in the deployment guide.
- The config loads when the working directory cannot be read, and an
  unreadable `.env` is named in the error.

## 0.2.0 (2026-10-12)

The admin console, a rebuilt Ira app, and the API behind both.

- **The Ira app at `/`** is built around the voice mark: the four bars are
  the mic, become the level meter while listening, and move with the spoken
  reply. Every state says in words what Ira is doing ("Checking find slots…").
  Each answer has "How Ira got this": the tools called, their arguments, the
  data they returned and the model that answered. The PIN card shows who may
  confirm, counts down, and covers every outcome: done (with who confirmed
  and when), wrong PIN with attempts left, locked until a time, expired,
  cancelled, already done, not allowed for the role, no PIN yet. Honest
  errors for a blocked mic, being offline, every model failing and an expired
  session. The menu lists today's conversations, restores them from the
  server, and lets each person set their own action PIN. Hands-free mode
  listens again after each spoken reply.
- **The admin console at `/admin`** (React 18, TypeScript, Vite; the build is
  committed so `pip install` needs no Node): sign in, a first-run setup
  wizard, accepting invitations, Today (questions, model calls, failures,
  cost, latency, by model, actions by status, channel health), conversations
  with full transcripts, actions with who proposed and who decided, tools
  with an on/off switch and a test form for read tools, models and voice
  with reorderable fallback chains and model tests, channels with pairing and
  install instructions, users and roles with invitations, tokens and
  sessions, the change log, the action audit log and cost per day. A left
  rail on desktop and a bottom bar on a phone; light, dark and system themes;
  every screen has empty, loading, error and "your role can't do this"
  states.
- **One set of design tokens** (`src/ira/web/static/tokens.css`) shared by
  the app and the console, with WCAG AA contrast in both themes and a
  Devanagari fallback in the font stack.
- **The console API**: first-run setup with a one-time code, invitations by
  link, per-user PINs, role changes, API tokens, tool switches and tests,
  model chains and tests, settings, sessions, a change log, costs per day,
  typed stream events with tool arguments and results, paging with
  `X-Has-More`, action counts, the server's bound and public address,
  Telegram pairing from the console, voices and cooling reasons, and the
  model behind each stored answer.
- **CI** gains a `frontend` job: Node 22, typecheck, tests, build, and a
  check that the committed build matches the source.

## 0.1.0 (2026-10-12)

The first public alpha: the assistant loop, the model gateway with fallback
chains and cost logging, read and action tools, PIN-confirmed actions, the
web chat, the HTTP API, Telegram, voice in and out, the clinic example, tests
and secret scanning.
