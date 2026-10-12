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

## Set up from the browser instead

`ira setup` needs a terminal on the server. Without one (a container, a
service manager), just start `ira serve`. While no account exists it prints
a one-time **setup code** and a link that carries it:

```text
Ira is listening on http://127.0.0.1:8765  (API docs: /v1/docs)

    No account exists yet. To create the owner account, open:

        http://127.0.0.1:8765/admin/setup#code=7F3A-91C2-0B4E

    or enter the setup code 7F3A-91C2-0B4E on that page. It works once, and only
    until the owner exists. (`ira setup` in a terminal does the same.)
```

Open the link, choose the owner's email and password, and you are signed in.
Until the admin console is built into the package, the link opens the chat
page at `/` instead, and its setup form asks for the code.

- The code is only shown where the server's output goes (the terminal, or
  `journalctl -u ira` under systemd), so someone who merely reaches an
  exposed server cannot claim it.
- It works once. As soon as the owner exists, the setup routes answer `409`.
- Wrong codes are throttled: five from one address lock that address out
  for 15 minutes.
- On a server bound to `0.0.0.0`, the printed link uses `127.0.0.1`; open the
  same path on your server's address instead.

Then set your action PIN: `ira pin set` on the server, or
`PUT /v1/me/pin` over the API, which asks for your password again.

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
