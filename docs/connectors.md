# Your connections

A connection lets Ira use another service for you: GitHub today, and any
service with an MCP server. Each person has their own connections; nobody
else sees them or their tokens, not even the server's owner.

Ira talks to connected services through the
[Model Context Protocol](https://modelcontextprotocol.io) (MCP), with the
official Python SDK, which speaks the current version of the protocol
(2026-07-28) and the earlier ones. Install it on the server with the
`connectors` extra:

```bash
pip install "ira-assistant[connectors]"
```

## Connect GitHub (read-only)

1. On github.com, make a **fine-grained personal access token**
   (Settings, Developer settings, Personal access tokens), for the
   repositories you choose, with read access.
2. In the Ira app: menu, **Your connections**, **GitHub (read-only)**. It
   fills in GitHub's own MCP server, `https://api.githubcopilot.com/mcp/readonly`
   ([GitHub's guide](https://docs.github.com/en/copilot/how-tos/provide-context/use-mcp/use-the-github-mcp-server)).
3. Paste the token, type your PIN and **Connect**.

Ira then lists the server's tools under **Tools**. Ask: "IRA repo mein
kitne issues khule hain?" For write access, use the address without
`/readonly` and a token that may write; every change then waits for your
yes or your PIN (below).

## Any MCP server

**Connect a service** takes a name, the server's address and a token (sent
as `Authorization: Bearer`). The address must be `https://` and on the
public internet: the server refuses private and local addresses, so a
connection cannot make it reach machines on its own network. Its owner can
allow them (`connectors.allow_private: true`), for example to reach a
server on the same machine.

A server's owner can also offer **local** MCP servers, which run on the
server, in `ira.yaml`. People can never add a command themselves:

```yaml
connectors:
  mcp_servers:
    github:
      command: github-mcp-server
      args: [stdio, --read-only]
      person_env: [GITHUB_PERSONAL_ACCESS_TOKEN]   # each person gives their own
      description: GitHub, read-only
```

Each person then picks it under **Where** and gives their own value for
each `person_env` variable.

## Services that sign you in (OAuth)

Many MCP servers ask you to sign in with the service itself instead of a
token. Tick **Sign in with the service instead of a token**: Ira opens the
service's sign-in page; when you approve, the service sends your browser
back to this server (`/v1/connections/oauth/callback`), and the connection
finishes on its own. The MCP SDK does the protocol's part: it finds the
service's authorization server, registers Ira as a client, uses PKCE, and
checks that the answer belongs to this sign-in. The tokens are sealed like
any other secret and refreshed when they expire.

- This server's address must be one the service can send you back to:
  `channels.http.public_url`, or `http://127.0.0.1:<port>` on your own
  computer.
- You have 10 minutes to finish signing in.
- If the service ever wants you to sign in again, the connection says so
  and offers **Sign in**; Ira does not wait for it in the middle of an
  answer.

## What Ira may do with them

Every tool gets a tier, from what its server says about it, and only ever
stricter:

| The tool | Tier | So Ira |
| --- | --- | --- |
| marked read-only (`readOnlyHint`) | 0 | uses it when it helps |
| not marked, or writes something | 2 | reads back exactly what it will do, and waits for your yes |
| marked destructive (`destructiveHint`), or about sending, paying, sharing, deleting, merging or pushing | 3 | needs your PIN |

You may raise a tool's tier under **Tools**, never lower it below these. A
server's own description of its tools is a hint, so a tool called
`send_email` stays Tier 3 even if its server calls it read-only.

Whatever a connected service returns reaches the model marked as data,
never instructions, like a web page: a turn that read it cannot propose a
Tier 2 or 3 action. Each tool can be switched off, and so can the whole
connection (switching it back on needs your PIN). At most 40 tools of one
connection are offered at once; the rest start switched off.

## Your token

- It is **sealed** (AES-GCM) in the server's database, bound to its
  connection, and never shown again, logged or sent anywhere but its
  service.
- The key is `IRA_SECRET_KEY` (32 random bytes, URL-safe base64) or, if
  that is not set, `secret.key` next to the database, readable only by the
  server's user. Set the variable and keep it out of database backups: a
  copy of the database alone then opens nothing.
- **Remove** deletes the connection and its token. **Delete my data**
  deletes all of them; **Export my data** lists them, never their tokens.

## Google: Gmail and Calendar, read-only

Each person signs in with Google; Ira asks for `gmail.readonly` and
`calendar.readonly` only, and offers three Tier 0 tools: search mail (with
Gmail's own search words, such as `from:bank newer_than:7d`), read one
message, and list calendar events between two dates, in the person's own
time zone, across all their calendars.

The server's owner sets it up once, with their own Google Cloud project:

1. In the Google Cloud console, enable the **Gmail API** and the
   **Google Calendar API**.
2. Configure the **OAuth consent screen** (external), add the two scopes,
   and add each person who will use it as a **test user**.
3. Create an **OAuth client ID** of type *Web application*, with this
   server's address plus `/v1/connections/oauth/callback` as an authorized
   redirect URI (`https://ira.example.com/v1/connections/oauth/callback`,
   or `http://127.0.0.1:8765/...` on your own computer).
4. In `ira.yaml`, and the secret in `.env`:

    ```yaml
    connectors:
      google:
        client_id: 1234567890-abc.apps.googleusercontent.com
        client_secret_env: GOOGLE_CLIENT_SECRET
    ```

People then tap **Google (Gmail and Calendar)** under **Your connections**.

**Plainly:** Gmail's read scope is *restricted*. While the app stays in
Testing, Google ends each sign-in after 7 days, and the connection then
asks to sign in again. Publishing it for anyone needs Google's
verification, and for restricted scopes possibly a paid security
assessment. For one person or a family, Testing works; for mail without
that, use IMAP below. Not yet checked against a live Google account here:
the tests use a stand-in for Google's endpoints.

## Mail over IMAP, with an app password

Any mailbox (Gmail, Outlook, Zoho, your own), read-only, with no Google
sign-in: tap **Mail (IMAP)** and give the mail server (`imap.gmail.com`,
`outlook.office365.com`), your address and an **app password** made at
your provider (Gmail: Google Account, Security, 2-Step Verification, App
passwords). Ira opens the inbox read-only, so reading never marks a mail
as read. The app password is sealed like a token. Calendar still needs
Google's sign-in.

## Telegram, as you

The Telegram bot is for talking to Ira. This is different: Ira reads your
own chats and, after your yes, sends as you. It is opt-in, and needs:

1. Your own **api_id** and **api_hash**: sign in at my.telegram.org, then
   **API development tools**, and create an app (any name).
2. Under **Your connections**, **Telegram (as you)**: the two values, your
   phone number with its country code, and your PIN. Telegram sends you a
   code in the Telegram app; type it on the card (and your two-step
   password, if you set one).

Ira then has three tools: list your chats (Tier 0), read the latest
messages of one chat (Tier 0), and send a message to one chat by its exact
name (Tier 2: read back with the chat and the words, then your yes). When
two chats match a name ("Rahul"), Ira asks which one. The login session is
sealed like a token; **Remove** forgets it (also end it in Telegram's
Settings, Devices).

**Plainly:** Telegram allows clients made with your own api_id. Heavy
automation can get an account limited, so Ira reads only when you ask and
sends one confirmed message at a time.

## WhatsApp

There is no official WhatsApp API for personal accounts, and Ira will not
use an unofficial one: they break WhatsApp's terms and risk a ban. For a
business number, the WhatsApp Business Cloud API is the way. On a phone,
the Android app reads notifications, including WhatsApp's, and replies
through them, which is allowed.

## Coming next

A kit for connecting any business's API (`ira connector new`).
