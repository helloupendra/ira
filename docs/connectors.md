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

## Coming next

Google mail and calendar (read-only first; Gmail's scopes need Google's
verification for anything but test users, whose access lasts 7 days at a
time, and mail can also come in over IMAP with an app password), a
Telegram user client for reading and sending as you (opt-in), and a kit
for connecting any business's API. There is no official WhatsApp API for
personal accounts, and Ira will not use an unofficial one: the WhatsApp
Business Cloud API, for a business number, is the only way it will offer.
On a phone, the Android app reads notifications, including WhatsApp's,
and replies through them, which is allowed.
