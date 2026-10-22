# Design note: devices, Chrome and search (phase 1)

!!! note "Superseded"
    The Python companion and the Chrome extension this note describes are
    retired: [Ira for Mac](../clients/macos.md) does their work natively
    (files, the screen, browser tabs, coding tasks and the routine skill). The
    note stays as the record of the first design.

IRA so far answers over a business's own tools. Phase 1 makes it a personal
assistant too: a person pairs their own Mac, Ira reads a Chrome tab when
asked, watches it and says when it is done, and searches the web and the
news. Everything here is a generic IRA feature, off until a person turns it
on, and private to that person.

## Pieces

```text
Chrome extension --native messaging--> in.ira.mac host --unix socket--> ira-mac daemon
                                                                              |
                                                     WebSocket /v1/devices/ws (irad_ token)
                                                                              |
web app, console, Telegram <--events-- IRA server: device hub, assistant, search
```

- **Server** (`src/ira/devices/`, `src/ira/channels/devices.py`): devices
  and pairing, the WebSocket hub, per-user device tools, events, and the
  user's own settings, grants, audit, export and delete.
- **Mac companion** (`clients/mac/`): a LaunchAgent daemon holding the
  WebSocket, and a thin native-messaging host that Chrome starts.
- **Chrome extension** (`clients/chrome-extension/`): no network of its own,
  no resident content script; it injects a reader into one tab on request.
- **Search** (`src/ira/search.py`): `web_search` through the Brave Search
  API and `news_search` over RSS feeds named in `ira.yaml`.

## Data

New tables, all keyed by the user:

| Table | Holds |
| --- | --- |
| `devices` | id, user, kind (`mac`, `android`), label, token hash, created, last seen, revoked, client version, the tools of its last hello, the skills the user switched on |
| `device_pairings` | one-time pairing codes (hashed), kind, label, skills, 10-minute expiry |
| `device_events` | `watch_done`, `task_done`, `task_failed`: title and text (markup stripped), kept 7 days |
| `tool_log` | "What Ira did": who, channel, which tool, which device, tier, outcome, seconds. Never arguments or results |
| `user_settings` | per-person preferences: assistant name, wake phrase, languages, reply language, web search on or off |

`messages.private` marks a tool result that came from a device: only the
conversation's own user sees it; the admin transcript shows a placeholder.
`pending_actions` gains `tier`, `user_id` and `device_id`.

## Pairing and tokens

1. In the web app or the console, the person picks the kind, a name and the
   skills to allow, and confirms with their action PIN (a new grant is Tier 3).
2. The server answers with a one-time code (eight characters, 10 minutes, kept
   hashed) and a QR code of `https://<server>/pair#code=...`.
3. The device posts the code to `POST /v1/devices/pair` and receives its own
   token, `irad_` and 32 random bytes, once. Only its SHA-256 is stored.
4. The token works only on `GET /v1/devices/ws`; the rest of the API refuses
   it, and the WebSocket refuses every other credential. Revoking a device
   closes its connection at once.

## The WebSocket

JSON text frames, as the brief specifies: `hello` and `welcome`; `call` and
`result`; `event`; `ping` and `pong`. Limits: 1 MB frames, 25-second calls,
4 calls in flight, tool names `^[a-z][a-z0-9_]{2,40}$`, 30 tools, one event
per 30 seconds, 90 seconds of silence closes the connection. A new
connection for the same device replaces the old one, whose calls fail. A
hello with a bad tool list is refused with an `error` frame and close code
4400. Each tool in a hello may say its `skill` (default: the name up to the
first underscore) and its `tier` (default 2).

## Tools per person

Each turn of the assistant gets the registry's tools plus that user's own:
the tools of their connected devices whose skill they switched on, and the
search tools if they turned web search on and the server has it set up.
Nobody else's conversation sees them. When two of a user's devices offer the
same tool, it gains a `device` argument listing them.

## Tiers (the security model)

Every tool has a tier in code; the model's arguments can never change it.

| Tier | What | How it runs |
| --- | --- | --- |
| 0 | reading inside a grant | at once |
| 1 | small and undoable | at once; Ira says what it did |
| 2 | outward or costly | a proposal Ira reads back; runs on the user's "yes" (typed, spoken or tapped) within 120 s |
| 3 | money, deletion, sharing, push, merge, deploy, a new grant | the PIN-confirmed action, never a spoken PIN |

- `@tool` is Tier 0 and `@action` Tier 3 by default; both take `tier=`.
- A device declares each tool's tier in its hello.
- **Untrusted content cannot start Tier 2 or 3.** Device output and web
  results reach the model wrapped as `<device_output untrusted="true">` or
  `<web_results untrusted="true">`, with a system rule that they are data.
  If a turn has read any of it, a Tier 2 or 3 call in that turn is refused,
  and the person has to ask in their own words.
- Switching a skill on, pairing a device and turning web search on need the
  PIN. Switching anything off never does; an owner or admin can switch off
  anyone's grant, never switch one on.

## Events

A device's event is cut to 120 and 1,000 characters, stripped of markup, and
sent to its user only: the web app (server-sent events at
`/v1/me/events/stream`), their paired Telegram chats (text, and voice when
text-to-speech is set up), and their connected Android devices. One event per
30 seconds per device; the Mac companion queues to respect it.

## Privacy

- Page text and device output are read only when asked and kept only inside
  the conversation; an admin's transcript shows "(private device output)".
- "What Ira did" keeps no contents. "Export my data" returns a JSON file of
  the person's conversations, devices, events, settings and tool log.
  "Delete my data" removes them and revokes the devices, after the password.
- The Mac companion logs tool names, tab ids and timings, never page text or
  URLs with a query string. URLs it returns lose their query and fragment.

## Language

The system prompt says that people speak Hindi (Devanagari or romanised),
English and Hinglish, often in half sentences; to ask back when unsure; and
to reply in the language spoken, or in the person's chosen reply language.
With Polly, a reply with Devanagari is spoken as `hi-IN`, otherwise in the
configured code (Kajal speaks both). A small fictional evaluation set and
`ira eval language` measure intent and reply language against the configured
models; the numbers go in the docs before any claim.

## The Mac companion

- **Why two processes.** Chrome starts a native-messaging host itself, only
  while the extension holds a port, and speaks to it over stdio. The server
  connection must stay up when Chrome is closed, hold the Keychain token and
  later run tasks. So the daemon (a LaunchAgent) owns the WebSocket, and the
  host only relays frames to it over a Unix socket in a 0700 folder. The
  token never enters a process Chrome starts.
- **TCC.** launchd processes may not read `~/Documents`, so the runtime is
  installed under `~/Library/Application Support/ira-mac/` and phase 1 reads
  nothing under `~/Documents`.
- **Keychain.** Service `ira-mac`. `security` receives commands on stdin
  (`security -i`), so the token is never in argv, a file or a log.
- **Watches** run in the daemon: it reads the tab every few seconds and ends
  the watch on the text, idle time, 100%, a newly shown "Completed" or
  "Failed", the tab closing or the timeout. At most 5.

## Downloads

`/v1/downloads/` serves the Chrome extension zip and the Mac installer zip
from the package, and a release workflow attaches the same files to GitHub
Releases. Nothing is signed yet; no signing key is in the repository.
