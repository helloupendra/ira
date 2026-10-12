# Admin guide

Everything here is done with the `ira` command, run in the folder that holds
`ira.yaml` (or with `--config path/to/ira.yaml`, or `IRA_CONFIG`).

## First run

```bash
ira setup          # owner account; asks for email and password
ira pin set        # the action PIN (4-12 digits)
ira serve
```

Without a terminal, start `ira serve` first: while no account exists it prints
a one-time setup code, and the web page asks for it. The setup form and its
endpoint stop working as soon as the owner exists.

Both `ira setup` and `ira pin set` read from the terminal without echo. When
stdin is not a terminal they read one line from it, which is handy for
scripted installs:

```bash
printf '%s\n' "$OWNER_PASSWORD" | ira setup --email owner@example.com
```

## Users and roles

| Role | For |
| --- | --- |
| owner | the business owner; everything |
| admin | a trusted manager; everything except user management |
| staff | reception, shop floor: ask, voice, confirm actions with the PIN |
| viewer | someone who only needs the dashboards |

Add the others from the command line (the password is read without echo):

```bash
ira user add --email desk@example.com --role staff
ira user add --email accountant@example.com --role viewer
ira user list
```

Managing users from the admin console arrives in v0.2.

The **action PIN** is one per installation in v0.1: whoever confirms an action
must know it. Staff can propose and the owner can confirm on the same screen.

## API tokens

Programs (a phone shortcut, a script, another service) use tokens:

```bash
ira token create --label phone --scope ask
ira token create --label reports --scope admin.read
ira token create --label kiosk --scope ask,voice --user staff@example.com
ira token list
ira token revoke phone           # by label or id
```

The token is printed once; only its SHA-256 hash is stored. Scopes are
`ask`, `voice`, `actions` and `admin.read`, and they can only narrow the
owning user's role. Writing settings and managing users always need a signed-in
session, never a token.

## Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
2. Put the token in the environment (or `.env`) as `TELEGRAM_BOT_TOKEN`.
3. Enable the channel in `ira.yaml`:

   ```yaml
   channels:
     telegram:
       enabled: true
       token_env: TELEGRAM_BOT_TOKEN
       voice_replies: voice      # off | voice | always
   ```

4. Restart `ira serve`, then pair your chat:

   ```bash
   ira telegram pair              # or --user staff@example.com
   ```

   Send the printed `/pair CODE` to the bot within 10 minutes. The code works
   once and the bot deletes the message. The chat then acts as that user.

Commands: `/help`, `/new` (fresh context), `/cancel` (drop the pending
action), `/name <new name>` (owner or admin). To confirm an action, type the
PIN as a message on its own: the bot deletes it immediately and never sends it
to a model. A PIN said in a voice note is refused and that note deleted.

Group chats are ignored. Voice notes need the `ogg` extra or `ffmpeg`.

## Voice

```yaml
voice:
  stt:
    type: chat_audio             # or whisper
    provider: bedrock            # a provider defined under models.providers
    model: mistral.voxtral-small-24b-2507
    vocabulary: [Ira, Sunrise]   # names the transcriber should expect
  tts:
    type: polly                  # or openai
    voice: Joanna
    region: us-east-1
```

The browser mic needs a secure context: `http://127.0.0.1` works locally,
anything else needs HTTPS (see [Deployment](deployment.md)).

## Watching it

The admin API gives the numbers a console needs; with a token of scope
`admin.read`:

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/v1/admin/overview
```

`overview` returns today's calls, failures, cost, tokens, p50/p95 latency and
a per-model breakdown; `calls`, `conversations`, `actions`, `audit`, `tools`,
`channels`, `users` and `tokens` list the details. See [API](api.md).

## Backups

All state is in `data_dir` (default `./data`): `ira.db` plus whatever your
tools keep. Stop the server, or use `sqlite3 ira.db ".backup copy.db"`, and
copy the files. The data folder holds conversations and customer details:
treat backups as confidential.
