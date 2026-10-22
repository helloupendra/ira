# Devices

A **device** is something a person pairs with their own Ira: a Mac running
the companion, or (later) an Android phone that listens for "Hey Ira". A
device connects to the server over one WebSocket, offers tools, runs them
when Ira calls, and announces events ("the upload finished").

Devices are personal. A device belongs to one person; its tools are offered
only in that person's conversations, its events reach only that person, and
nobody else, an owner or admin included, sees what it returned.

## Pairing

1. On the Devices page (the Ira app's menu, or the console), the person picks
   the kind of device, names it, chooses the skills it may use, and enters
   their action PIN. A new device is a new grant, so it needs the PIN.
2. The server shows a **pairing code** (eight characters, `ABCD-EFGH`) and a
   QR code of `https://<server>/pair#code=ABCDEFGH`. The code works once,
   within 10 minutes, and only its SHA-256 hash is stored.
3. The device sends the code to `POST /v1/devices/pair` and receives its own
   **device token**: `irad_` and 32 random bytes, shown this once. The server
   keeps only its SHA-256 hash.

```http
POST /v1/devices/pair
{"code": "ABCD-EFGH", "kind": "mac"}
```

```json
{"device_id": 3, "token": "irad_...", "kind": "mac", "label": "Office Mac",
 "skills": ["chrome"], "name": "Ira", "websocket": "/v1/devices/ws"}
```

Five wrong codes from one address in 15 minutes give `429` for 15 minutes. A
used, expired or unknown code gives `410`.

## Tokens

- A device token works on `GET /v1/devices/ws` and nowhere else: the rest of
  the API answers `401`. Session and API tokens do not open the WebSocket.
- Send it as `Authorization: Bearer irad_...`. A client that cannot set
  headers may use `?token=`; IRA masks the value in every log line it writes,
  but a proxy in front may log it, so prefer the header.
- The Mac companion keeps it in the macOS Keychain, the Android app in the
  Android Keystore. Neither writes it to a file or a log.
- **Revoking** a device (`DELETE /v1/me/devices/{id}`, or an admin's
  `DELETE /v1/admin/devices/{id}`) stops the token at once and closes the
  device's connection with code 4403. Removing a person's account revokes all
  their devices.

## The WebSocket protocol

JSON text frames, each an object with a `type`.

**Hello.** The device's first frame, within 15 seconds:

```json
{"type": "hello", "kind": "mac", "label": "Office Mac", "version": "0.3.0",
 "tools": [
   {"name": "chrome_read_tab", "description": "Read one Chrome tab.",
    "parameters": {"type": "object", "properties": {"match": {"type": "string"}}},
    "skill": "chrome", "tier": 0}
 ]}
```

The server answers:

```json
{"type": "welcome", "deviceId": 3, "label": "Office Mac", "skills": ["chrome"],
 "assistant": "Ira", "wakePhrase": "Hey Ira"}
```

- `kind` must be the kind the device was paired as.
- Each tool has a `name` matching `^[a-z][a-z0-9_]{2,40}$`, a `description`,
  and `parameters` as a JSON Schema object (8 KB at most).
- `skill` is the grant the tool belongs to; it defaults to the name up to the
  first underscore (`chrome_read_tab` belongs to `chrome`).
- `tier` is the tool's tier: 0 reads, 1 small and undoable, 2 needs the
  person's "yes", 3 needs their PIN. A tool that does not say is Tier 2.
- A hello that breaks a rule gets `{"type": "error", "error": "..."}` and the
  connection closes with 4400.

**Calls.** The server calls a tool:

```json
{"type": "call", "id": "9b0c...", "tool": "chrome_read_tab", "args": {"match": "upload"}}
```

and the device answers with the same `id`:

```json
{"type": "result", "id": "9b0c...", "ok": true, "content": {"summary": "Upload: 63%"}}
{"type": "result", "id": "9b0c...", "ok": false, "error": "no tab matches 'upload'"}
```

`content` is any JSON. A `summary` string in it is what a no-key demo reads
out, and helps a model too.

**Events.** The device announces something its person should hear:

```json
{"type": "event", "event": "watch_done", "title": "Upload finished",
 "text": "The Upload tab reached 100%.", "data": {"tabId": 812}}
```

`event` is `watch_done`, `task_done` or `task_failed`.

**Keepalive.** Either side sends `{"type": "ping"}` every 30 seconds and the
other answers `{"type": "pong"}`.

**Goodbye.** A device being uninstalled may send `{"type": "bye"}` instead of
a hello: the server revokes its token and closes the connection.

## Limits

| Limit | Value | What happens |
| --- | --- | --- |
| Frame size | 1 MB | the connection closes with 1009 |
| A call | 25 seconds | the model is told the device did not answer |
| Calls in flight | 4 per device | a fifth is refused at once: "the device is busy" |
| Tools | 30 per device | the hello is refused |
| Events | 1 per 30 seconds per device | an `error` frame; send it again later |
| Silence | 90 seconds | the connection closes with 4408 |
| Connections | 1 per device | a new one replaces the old (4000), whose calls fail |

## Security

- **Grants.** A device's tools are offered only while their skill is
  switched on, by the device's own person, with their PIN. Anyone may switch
  a skill off without a PIN; an owner or admin can switch off anyone's,
  never switch one on.
- **Tiers.** Tier 0 and 1 tools run when Ira calls them. A Tier 2 or 3 tool
  becomes a proposal: Ira reads it back, and it runs on the device only after
  the person's "yes" (Tier 2) or PIN (Tier 3). The tier comes from the
  device's hello, never from the model.
- **Untrusted output.** What a device returns reaches the model inside
  `<device_output untrusted="true" from="...">...</device_output>`, with a
  rule that it is data, never instructions. Once a turn has read a device's
  output, it cannot propose a Tier 2 or 3 action.
- **Privacy.** A device's output is kept only in its person's conversation,
  marked private: an admin reading that conversation sees a placeholder, and
  the parameters of an action on someone's device are hidden from everyone
  else. "What Ira did" records each call with no arguments or results.
- **Events** are cut to 120 characters (title) and 1,000 (text), stripped of
  HTML and markdown, kept seven days (200 per person at most), and sent only
  to their person: the web app's live stream (`GET /v1/me/events/stream`),
  their paired Telegram chats (text, and voice when text-to-speech is set
  up), and their connected Android devices.

## Adding a device of your own

Any program that speaks the protocol can be a device. In outline:

1. Pair it: ask the person for the code, `POST /v1/devices/pair`, and keep
   the token somewhere safe (never in a log).
2. Connect to `/v1/devices/ws` with the token, send a hello with your tools
   and their tiers, and wait for `welcome`.
3. Answer each `call` with a `result` carrying the same `id`, within 25
   seconds. Validate the arguments yourself: the model wrote them.
4. Send `ping` every 30 seconds, answer the server's pings, and reconnect
   with a growing delay when the connection drops.
5. Keep events to one per 30 seconds; queue the rest.

The Mac companion in `clients/mac/` is a complete example in Python.
