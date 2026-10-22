# Getting started

## Install

IRA needs Python 3.11 or newer.

```bash
git clone <this repository> ira && cd ira
python -m venv .venv && source .venv/bin/activate
pip install -e .                 # or: uv pip install -e .
```

Optional extras:

| Extra | Adds | Install |
| --- | --- | --- |
| `aws` | SigV4 signing for Amazon Bedrock (Mantle) and Amazon Polly | `pip install -e ".[aws]"` |
| `ogg` | Decoding Telegram voice notes (OGG/Opus) with `soundfile` | `pip install -e ".[ogg]"` |
| `dev` | pytest, ruff, pre-commit, detect-secrets | `pip install -e ".[dev]"` |

On PyPI the distribution is called `ira-assistant`; the command and the
import name are `ira`.

## Run the demo (no API key)

```bash
cd examples/clinic
ira demo seed      # fictional appointments for the next week
ira setup          # the owner account: email and a 10+ character password
ira pin set        # the owner's action PIN: 4-12 digits
ira serve          # http://127.0.0.1:8765
```

Open the page, sign in and ask:

- `what are the clinic hours?`
- `find slots tomorrow`
- `show appointments for Avery`
- `cancel appointment 3`

The last one shows a confirm card. Type the PIN to run it, or Cancel. The
demo provider matches keywords rather than understanding language; with a
real model you can talk normally.

## Set up from the browser: the setup wizard

`ira setup` needs a terminal on the server. Without one (a container, a
service manager), just start `ira serve`. While no account exists it prints
a one-time **setup code** and a link that carries it:

```text
Ira is listening on http://127.0.0.1:8765  (API docs: /v1/docs)

    No account exists yet. To create the owner account, open:

        http://127.0.0.1:8765/admin/setup#code=7F3A-91C2-0B4E

    or enter the setup code 7F3A-91C2-0B4E on that page. It works once, for 24
    hours, and a restart keeps it. `ira setup --new-code` replaces it;
    `ira setup` in a terminal creates the owner here instead.
```

The link opens the console's setup wizard with the code already filled in.
Its six steps:

1. **The owner's account**: email and a password of ten characters or more.
   You are signed in as soon as it is created.
2. **Name and voice**: what the assistant calls itself, and the
   text-to-speech voice when one is configured. Both can be changed later
   under Models & voice.
3. **Model provider**: which models answer, and whether each provider's key
   is set in the server's environment. Keys are never typed into the browser:
   put them in the environment or in `.env` next to `ira.yaml` and restart
   `ira serve`. The free demo router works with no key at all.
4. **Action PIN**: your own 4 to 12 digit PIN, which releases actions. It
   asks for your password again.
5. **Channels**: the web app, the HTTP API, Telegram pairing and how to
   install the app on a phone.
6. **Done**: open Ira, open the console, or invite your staff.

You can close the wizard at any step and come back to `/admin/setup`: it
remembers where you were. The code itself is only used in step 1.

- The code is only shown where the server's output goes (the terminal, or
  `journalctl -u ira` under systemd), so someone who merely reaches an
  exposed server cannot claim it.
- It works once. As soon as the owner exists, the setup routes answer `409`.
- It lasts 24 hours, and a restart keeps it: the server prints the same link
  again. After 24 hours the next start (or the next try) makes a new one and
  logs it. `ira setup --new-code` replaces it at once, and the old link stops
  working.
- Wrong codes are throttled: five from one address lock that address out
  for 15 minutes.
- On a server bound to `0.0.0.0`, the printed link uses `127.0.0.1`; open the
  same path on your server's address instead.
- If the console's files are missing (a source checkout without
  `src/ira/web/admin`), the link opens the Ira app at `/` instead, and its
  own setup form asks for the same three things.

## Action PINs

Each person has their own PIN, and confirms actions with it. `ira pin set`
sets the first owner's; `ira pin set --user desk@example.com` sets someone
else's. Who may confirm is set in `ira.yaml`:

```yaml
actions:
  confirm_roles: [owner, admin, staff]   # the default
  tools:
    cancel_appointment:
      confirm_roles: [owner]             # only an owner confirms cancellations
```

An installation upgraded from v0.1, which had one PIN for everyone, gives
that PIN to every owner, admin and staff account on its first start; each
person can then change theirs.

## Use a real model

Add a provider in `ira.yaml`, put it first in the `default` tier, and set its
key in the environment (or in a `.env` file next to `ira.yaml`):

```yaml
models:
  providers:
    openai: { type: openai, api_key_env: OPENAI_API_KEY }
    demo:   { type: fake }
  tiers:
    default: [openai:gpt-4o-mini, demo:router]
```

```bash
export OPENAI_API_KEY=...        # never put it in ira.yaml
ira serve
```

Any OpenAI-compatible server works the same way with a `base_url`, including
local ones (llama.cpp, vLLM, Ollama). See `ira.example.yaml` in the
repository root for every option.

## Start your own folder

`ira init` makes a new folder for one business: a commented `ira.yaml`, a
`tools.py` with one read tool and one action tool to replace, a README and a
`.gitignore`. It refuses a folder that is not empty and never writes a
secret.

```bash
ira init ~/ira/shop --business "Example Shop, a hardware store"
ira init ~/ira/clinic --provider bedrock --port 8811 --public-url https://clinic.example.com
```

| Option | Default | |
| --- | --- | --- |
| `--name` | `Ira` | The assistant's name |
| `--business` | `your business` | One line about the business, for the model |
| `--port` | `8765` | Its port on `127.0.0.1` |
| `--provider` | `demo` | `demo`: the keyword router, no key. `bedrock`: Amazon Bedrock models, Voxtral speech-to-text and Polly speech, signed by your AWS credentials |
| `--region` | `us-east-1` | The Bedrock Mantle region (bedrock only) |
| `--voice` | `Kajal` | The Polly voice, Indian English (bedrock only) |
| `--public-url` | none | The address people open, for the links Ira sends |

Then check it with `ira doctor`:

```bash
cd ~/ira/shop
ira doctor --no-models     # config, data folder, port, tools, owner: no calls
ira serve                  # prints the one-time setup link
ira doctor                 # once the owner has a PIN: models and voice too
```

Each check prints `ok`, `warn`, `FAIL` or `skip`, and the command exits
non-zero when anything failed. It opens the database read-only and never
creates it or the data folder, so it is safe to run against a live instance.
Run it as the user that runs IRA.

## Try the API

```bash
ira token create --label laptop --scope ask
curl -s http://127.0.0.1:8765/v1/ask \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"text": "find slots tomorrow"}'
```

Interactive API docs are at <http://127.0.0.1:8765/v1/docs>.

## Next

- Write tools for your own data: [Concepts](concepts.md#tools).
- Add Telegram and voice: [Admin guide](admin-guide.md).
- Put it on a server: [Deployment](deployment.md).
