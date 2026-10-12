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
ira pin set        # 4-12 digits; releases actions
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

!!! tip "No terminal for setup?"
    If you start `ira serve` before `ira setup`, the server prints a one-time
    **setup code** in its log, and the web page shows a setup form that asks
    for it. The form stops working as soon as an owner exists.

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
