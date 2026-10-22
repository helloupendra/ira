# Changelog

## [Unreleased]

### Your own Ira: devices, Chrome and search

Anyone can now run Ira as their own assistant, on their own server or as one
person on a shared one. Everything below is per person and off until they
switch it on.

- **Devices.** A person pairs a Mac (later, an Android phone) with a one-time
  code or QR code and their PIN. The device trades the code for its own
  `irad_` token, kept only as a hash and valid only on the device WebSocket
  (`/v1/devices/ws`). Its tools are offered only in its owner's
  conversations, only while the skill they belong to is switched on, and its
  events ("the upload finished") reach only its owner: the web app, their
  Telegram chats and their Android devices. Limits: 1 MB frames, 25-second
  calls, 4 in flight, 30 tools, one event per 30 seconds, one connection per
  device. Revoking a device disconnects it at once.
- **The Mac companion** (`clients/mac/`): a LaunchAgent that holds the
  WebSocket and keeps its token in the Keychain, a thin Chrome native
  messaging host, and three tools: list Chrome's tabs, read one tab (title,
  address without its query, visible text, progress), and watch a tab until
  it finishes. `install.sh` and `uninstall.sh` are safe to run again.
- **Ira for Chrome** (`clients/chrome-extension/`): a Manifest V3 extension
  with no network of its own and no resident script. Its reader is injected
  into one tab on request and never reads form fields or passwords.
- **Downloads**: `/v1/downloads` serves the Mac installer and the extension,
  and a workflow attaches them to each `v*` release. Nothing is signed yet.
- **Web and news search**: `web_search` through the Brave Search API
  (`BRAVE_SEARCH_API_KEY`, 30 an hour per server) and `news_search` over RSS
  and Atom feeds in `ira.yaml`, both switched on per person with the PIN.
- **Tiers.** Every tool declares a tier in code: 0 reads, 1 small and
  undoable, 2 needs a "yes" from the person who asked (typed, spoken or
  tapped), 3 needs a PIN. Untrusted results (web pages, device output) reach
  the model wrapped as data, and a turn that read them cannot propose a Tier
  2 or 3 action. Pairing a device, switching a skill on and turning web
  search on need the PIN.
- **What Ira did**: every tool call and action, with device, tier, outcome
  and time, never contents (`GET /v1/me/activity`).
- **Your assistant**: each person names it, sets a wake phrase, and picks the
  languages they speak (Hindi, English, Hinglish) and the reply language.
  Polly speaks a Devanagari reply as Hindi.
- **Privacy**: an admin reading someone's conversation sees "private" instead
  of their device's output; "Export my data" and "Delete my data"; grants
  listed with "turn off" for each person and for owners and admins.
- The Ira app gains **Your devices**, **Your assistant**, **What Ira did**
  and **Your data**, and speaks device events as they arrive. The console
  gains a **Devices** screen.
- **Learning, if a person wants it.** Off by default; switched on with the
  PIN, source by source: a Mac's lock, sleep and network (by a salted hash
  the person names), iPhone Shortcuts reporting places, what they say about
  where they are going (kept only if the quote is word for word theirs),
  and thumbs on answers. A nightly learner finds routine times, commute
  durations and answer preferences, writes each as a sentence whose every
  number is in its evidence, and asks once; only a yes puts it in the
  assistant's context. Reminders by time or place (`remind_me`), and an
  optional nudge 15 minutes before a routine. Each person has a time zone,
  set from their browser. The Ira app's **What Ira knows about you** holds
  the switches, named places, learnings (yes, no, reword, forget),
  reminders and an iPhone Shortcuts key; a question in the chat has Yes and
  No buttons, and answers get thumbs when that source is on. See [What Ira
  learns](docs/learning.md).
- New docs: [Your own Ira in 15 minutes](docs/personal-assistant.md), [the Mac
  companion](docs/clients/mac.md), [Privacy](docs/privacy.md),
  [Devices](docs/devices.md), and a design note.
- **`ira eval language [--spoken]`**: a small fictional set of Hindi, English
  and Hinglish requests, scored for intent, reply language and (spoken by a
  macOS voice) transcription. Four runs with Bedrock models, typed, scored
  92-100% on both intent and reply language; the numbers and the misses are
  in [Hindi, English and Hinglish](docs/language.md). Speech is not measured
  yet: Bedrock's Mantle endpoint refuses audio for Voxtral.
- **Amazon Transcribe streaming** as speech-to-text (`voice.stt.type:
  transcribe`): Hindi and English identified per recording, switching inside
  one for Hinglish, over Transcribe's WebSocket API with a presigned URL.
  Not yet checked against a live account. `ira eval language --spoken
  --voice polly` speaks the requests with Polly, so a Linux server can
  measure hearing too.
- **Half sentences**: when a tool that only reads can settle what was meant,
  Ira looks first and asks only when looking would not help.
- `GET /admin` without a trailing slash redirects to the console.
- **Speech in the browser.** When the server has no speech-to-text, the
  Ira app recognises speech with the browser's own engine (`hi-IN` or
  `en-IN`, from the person's languages) and sends only the text
  (`voice.browser_stt`: `fallback` by default, `prefer`, `off`). Chrome
  sends that audio to Google; the privacy page says so.
- **Passwords and emails can change.** Each person changes their own
  password (their other sessions end) and email under Tokens & security,
  with their password again; an owner sets someone's password or email from
  Users & roles; `ira user password` and `ira user email` do it from the
  server. All go to the change log.
- **A typed pairing code finds its server.** A Mac zip downloaded from an
  IRA server carries that server's address, so typing the code works; with
  no address known the companion asks instead of trying this Mac. The
  pairing card offers the link first.
- **The setup link survives restarts.** The setup code is kept in the
  database for 24 hours, so a link already handed out keeps working after a
  restart; `ira setup --new-code` replaces it.

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
