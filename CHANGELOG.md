# Changelog

## [Unreleased]

### Your own Ira: devices, the Mac and search

Anyone can now run Ira as their own assistant, on their own server or as one
person on a shared one. Everything below is per person and off until they
switch it on.

- **The cost log counts every attempt.** One row per attempt at a model,
  however it ends (answered, failed, timed out or cut off), grouped by
  request; a cost that is not known is "unknown", never $0.00; and input
  read from a provider's cache is priced as cached (`cached_input` and
  `cache_write` in the price table).
- **Retention.** The logs that only grow are kept to days set under
  `retention` in `ira.yaml`, cleaned every hour: live-call timings 30 days,
  ended sessions and unused codes 30 after they end; model calls, "What Ira
  did", the audit log and the change log until the owner sets days.
  Conversations and Drop keep their own rules. New indexes, and the admin
  pages read on their own connection, so they never hold up a live call.
- **Drop.** A private inbox shared by your own devices: send text, a link or a
  file (95 MB) from one, and it is on the others at once. Kept 30 days, 2 GB
  each, encrypted at rest with the server's key (not end to end), removed with
  your data. Its own permission, `drop`: a Siri key cannot read it. Ira can
  list it and send to it. On Telegram, `/drop` puts text or a file in it, and
  new items come to the paired chat once the person switches that on (off by
  default, and for those who never touched it). In the Ira app: a
  tray at the top with Copy first, files by picker, drag or paste, live from
  the other devices, and Share → Ira once the app is installed on Android
  (shown first, sent only on Send to Drop). On Android: a Drop screen,
  Share → Ira Drop with a confirm and progress, a Send clipboard tile, and a
  notification with Copy while Ira is open. On the Mac: the newest items in
  the menu-bar menu, files and text dragged onto the icon, ⌃⌥⌘V to send the
  clipboard and ⌃⌥⌘C to copy the newest item, a notification with Copy, and
  files saved to ~/Downloads/Ira. Ira for Mac now refuses a tool whose skill
  is off for it, whatever the server asks, and `~/LIBRARY` like `~/Library`.
  On the iPhone: a Drop screen with Copy first, files fetched then saved or
  opened through the share sheet, Share → Ira Drop from any app (shown
  first, sent only on Send to Drop), and a notification with Copy while Ira
  is open.
  From a terminal:
  `ira drop login`, then `send`, `list`, `get` and `rm`.
  `POST/GET/DELETE /v1/me/drop`, `/v1/me/drop/settings`.
- **Devices.** A person pairs a Mac (later, an Android phone) with a one-time
  code or QR code and their PIN. The device trades the code for its own
  `irad_` token, kept only as a hash and valid only on the device WebSocket
  (`/v1/devices/ws`). Its tools are offered only in its owner's
  conversations, only while the skill they belong to is switched on, and its
  events ("the task is done") reach only its owner: the web app, their
  Telegram chats and their Android devices. Limits: 1 MB frames, 25-second
  calls, 4 in flight, 30 tools, one event per 30 seconds, one connection per
  device. Revoking a device disconnects it at once.
- **Ira for iPhone** (`clients/ios`), a native app paired as device kind
  `ios`: typing, a live call with barge-in or the iPhone's own speech
  recognition when the server has no live voice, "Hey Siri, Ask Ira", "Tell
  Ira" and "Talk to Ira" as App Shortcuts, Yes or No and the typed PIN for
  proposals, Report, and the tools iOS allows (contacts, calendar,
  reminders, location, a call after the person's yes and tap). CI builds it
  for the simulator and tests it there against a local Ira; TestFlight
  steps are in the iPhone guide. A database from before keeps its devices.
- **Downloads**: `/v1/downloads` names Ira for Mac (`Ira.dmg`) on the
  project's latest release, where a macOS runner attaches it for each `v*`
  tag. It is signed ad hoc until there is a Developer ID.
- **Retired before release:** the Python Mac companion (`clients/mac`) and
  the Ira for Chrome extension, built first, are gone. Ira for Mac does
  their work natively, takes over a companion's pairing and network code,
  and removes it; the old download names answer 404 with a pointer.
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
- New docs: [Your own Ira in 15 minutes](docs/personal-assistant.md), [Ira
  for Mac](docs/clients/macos.md), [Privacy](docs/privacy.md),
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
- **"News chalao" plays.** `video_find` finds a news channel's live stream
  or a video, and Ira opens its watch link on the phone or Mac, which
  plays it. YouTube's own search API (with a key) or Brave's, never its
  pages.
- **New Bedrock instances hear with Transcribe.** `ira init --provider
  bedrock` (and `ira-add-business`) now write Amazon Transcribe streaming in
  ap-south-1 for speech, not Voxtral, which Bedrock refuses; the example
  role policy allows it.
- **A device's skills, saved together.** On the device card, ticking only
  marks changes; Save sends them all, with one PIN when any is switched on
  and none to switch off. Select all and Select none, and each row says
  what happened.
- **Trusted apps.** A person may name apps on a device (YouTube) where Ira
  taps and types without asking while that app is in front; adding one
  takes the PIN.
- **A fingerprint instead of the PIN.** A phone or Mac enrols a key that
  only the person's fingerprint or face unlocks, once, with the PIN; it
  then confirms an action by signing it. A wrong signature counts as a
  wrong PIN.
- **Approval windows.** One PIN on a screen or app action on a device lets
  the next such steps there run without asking, for 15 minutes (each person
  chooses off or 5 to 60, under **Your assistant**, with **Stop**).
  Sending, calls, payments, deleting and new grants always ask. The
  fingerprint approval and trusted apps are designed in the security page.
- **Deploys wait for calls.** `ira-restart-when-quiet <name>` restarts an
  instance once no live call is open on it (the server keeps the count in
  `data/live-calls.json`), or after 10 minutes.
- **Restarts are quick.** As it stops, the server closes devices and live
  calls with 1001 (going away) and ends event streams, and waits 5 seconds
  at most for the rest; the service unit stops within 15. A restart no
  longer hangs for 90 seconds. A phone hanging up mid-answer is logged as
  information, not an error.
- **No stray Chinese.** Chinese, Japanese and Korean characters are taken
  out of an answer to someone who does not write them; a mostly Chinese
  answer is asked for again, or excused in the person's language.
- **Only others' text taints a turn.** A device's status ("Opened YouTube")
  and the person's own contacts or call log no longer block the next action.
- **A confirmed action carries on.** After a yes or a PIN, the model sees
  what the action returned, or why it failed, and goes on with the request;
  the app shows its answer, and a live call speaks it. Before, the model
  kept seeing the action as waiting and asked for the PIN again.
- **Skills that are off are named.** Ira knows which skills a device has
  but the person has not switched on, and says so ("Calls is off on Pixel
  7: switch it on under Your devices") instead of looking elsewhere.
- **A tool call written as text runs.** Some models write their call into
  the answer; it now runs when it names an offered tool, and is never shown
  or spoken.
- **Out of steps, still an answer.** When a request uses up its tool rounds
  (now 8 by default, from 6), Ira says what it tried, what it found and
  what to do next, in the person's language. And it searches for a file,
  folder or contact with at most three forms of the name, then says so.
- **Ira on iPhone.** The web app installs to the Home Screen and its live
  call works in Safari: sound starts on the tap, the silent switch does not
  mute a call, and the screen stays on. "Hey Siri, Ask Ira" is a Shortcut
  with a token that can only ask, made under **Siri on iPhone** with the
  PIN. See Ira on iPhone in the docs.
- **Your businesses.** A profile for each business a person works with:
  what it is, its people, its terms, and what Ira may do for it. Ira keeps
  them in mind, and updates one when told ("Sunrise pays in 30 days").
- **The connector kit.** `ira connector new <name>` writes a tool pack for
  any business's API: one tool per operation from an OpenAPI description,
  three general tools from a base URL, or one that asks another Ira with an
  ask-only token. Reading is Tier 0, changes Tier 2 with the exact call read
  back, deleting Tier 3.
- **A pairing code for app reviewers.** `ira device code --email ... --days 7
  --uses 3` makes a code that lasts up to 14 days and pairs up to 10
  devices, from the server's command line only.
- **Report an answer.** Every answer in the Ira app has **Report** (wrong,
  harmful, offensive, private, other, and a note); the phone and Mac apps
  use the same `POST /v1/me/reports`. Owners and admins read them under
  **Reported answers** in the console and mark them dealt with.
- **A paired device may talk to Ira for its person**, over HTTP too: ask,
  stream, voice and confirm actions, with at most those permissions of the
  person's role. It still never changes settings, pairs or manages
  anything, and revoking it stops it everywhere.
- **Your connections** ([Your connections](docs/connectors.md)): each
  person connects MCP servers, remote (GitHub's own, read-only, is one
  tap) or local ones the operator offers, with the official MCP SDK
  (the `connectors` extra). Tiers come from each tool's annotations and
  only get stricter; output is untrusted; tokens are sealed with AES-GCM
  and never shown again. Remote servers on private addresses are refused
  unless allowed. Google (Gmail and Calendar, read-only, through the
  owner's own OAuth client) and any mailbox over IMAP with an app password
  are built in, and so is Telegram as you (a user client with the
  person's own api_id; sending is Tier 2). Services that sign you in
  (OAuth) work too: Ira opens
  their page and finishes when the browser comes back. A confirmed Tier 2
  or 3 action of a connection runs through that person's own tool.
- **A general assistant.** Ira plans across tools on any of the person's
  devices and connections (the call log, then the contacts, then the
  call), and asks which one when a target is unclear. It remembers the
  people the person names ("Rahul Sharma mera CA hai") with
  `remember_person` and `forget_person`.
- **Real-time voice** ([Real-time voice](docs/realtime.md)):
  `/v1/voice/live`, a live call over a WebSocket for the Ira app, the Mac
  app and the Android app. Audio only while you speak, Amazon Transcribe
  streaming (Hindi preferred, English identified), the same assistant with
  its tools and tiers, and each sentence spoken by Polly as soon as it is
  written. Speaking while Ira talks stops it. Calls get short spoken
  answers, and "Ek second" when a tool is needed first. `ira eval live`
  measures end of speech to first word: p50 1.7 to 2.2 s, p95 5.1 to 5.6 s
  on the first server. The Ira app has a live call (the phone button):
  its voice detector runs in the browser, and audio goes up only while
  you speak. On a call, a proposed action is read back with its exact
  target. Macs can now be offered the `files` and `screen` skills, for
  the native Mac app.
- **Ira for Mac** (`clients/macos/`, [guide](docs/clients/macos.md)): a
  native menu-bar app, opened with Option-Space, that pairs in the app (a
  link or a code), keeps its key in the Keychain, and offers `files_find`
  (Spotlight), `file_read` (PDF, Word, RTF, text), `file_open` and
  `screen_read` (the front window's text, read on the Mac with Vision). Talk
  by typing or by voice over `/v1/voice/live`, with barge-in; servers without
  live voice use the HTTP API, both with the device token. Built with SwiftPM
  alone into `Ira.app`, a zip and a dmg, in CI on a macOS runner; a
  one-time local signing identity keeps permissions between builds.
  The Mac's own abilities follow, each behind a skill and a tier: browser
  tabs in Chrome, Safari, Arc, Edge and Brave (titles and addresses, then
  the screen), Contacts, calendars and reminders (EventKit), Mail search,
  read and draft, Notes, iMessage, apps, web pages, VS Code, the clipboard,
  Shortcuts, the routine skill, and coding tasks in a sandboxed git worktree
  with VS Code open on it (progress, done and failed as events), whose
  branch is pushed only after the PIN and never to a protected default
  branch. A first-run checklist, permissions shown in Settings, an optional
  on-device "Hey Ira", a pin to keep the window on top, a live "working"
  row, a PIN box for Tier 3, deadlines on every tool, and "Remove Ira from
  this Mac". Every Mac skill can be ticked at pairing, and devices may send
  `task_progress`. Permissions are kept per build: a rebuilt Ira says so in
  its checklist and asks macOS to list it for Screen Recording, and a search
  asks macOS about Documents, Desktop and Downloads itself, or says which
  switch in Files and Folders is off. The **control** skill lets Ira use
  the Mac like a person, through Accessibility: `mac_click` (by a
  control's label, or where the words are written), `mac_type`,
  `mac_keys`, `mac_scroll` and `mac_menu`, each Tier 3 and covered by an
  approval window, never in password fields, password managers, System
  Settings' private pages or the Apple menu. To stay within 30 tools, a few
  merged: `mail_search` and `notes_search` read one item by id,
  `reminders_set` adds or completes, `file_open` opens in VS Code, and
  `code_task_status` lists tasks without an id. While an approval window
  is open, the window shows how long with **Stop** and the menu-bar mark
  is orange; Touch ID can confirm instead of the PIN (a Secure Enclave key
  enrolled once with the PIN); trusted apps are listed with a link to the
  web page that changes them (`/#panel=assistant` now opens that page);
  and every `screen_read` and control result names the app in front by
  its bundle id.
- **Ira for Android** (`clients/android/`, [guide](docs/clients/android.md)):
  Kotlin and Compose, Android 10 and later. Pairs with a link or a code and
  keeps its key encrypted with an Android Keystore key. Live voice over
  `/v1/voice/live` with an on-phone voice detector, sentence-by-sentence
  playback and barge-in, in a microphone foreground service on only during
  a call; typing works too. Becomes the digital assistant (a long press of
  the power button). Offers the phone to Ira as a device: calls, contacts,
  SMS, notifications and direct reply, alarms, timers, reminders, calendar,
  apps, maps, media, location and settings, each behind a skill and a tier.
  Two builds: one for Google Play, with SMS and call log only while it is
  the default assistant and no Accessibility service, and a sideloaded
  personal build that adds them; the docs give the policy matrix and a
  Play Console guide. CI runs its unit tests and builds both debug APKs.
  Version 3 (0.3.0) adds Drop, approves with a fingerprint only (never the
  screen lock), answers Yes and No by the action's id, ends a call when the
  phone rings, and keeps release builds out of screenshots.
- **Tasks on your Mac** (the `tasks` skill): Ira hands a job to a coding
  agent configured on the Mac, in a new git worktree and branch of a
  repository the person allowed there. It runs in macOS's sandbox, its git
  cannot push, and Ira reports the files changed and the tests. Starting a
  task needs a yes; pushing its branch needs the PIN. Now part of Ira for
  Mac.
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
