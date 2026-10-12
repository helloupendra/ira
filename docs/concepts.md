# Concepts

## Tools

A **tool** is a Python function Ira may call. Register it with a decorator:

```python
from typing import Annotated
from pydantic import Field
from ira import tool


@tool
def find_slots(
    date: Annotated[str, Field(description="YYYY-MM-DD, 'today' or 'tomorrow'")],
) -> dict:
    """Free 30-minute appointment slots on one day."""
    ...
```

- The **name** is the function name (or `@tool(name=...)`).
- The **description** is the first paragraph of the docstring.
- The **arguments** come from the signature, or from a single pydantic model
  parameter. They become the JSON schema the model sees *and* the validation
  applied before your function runs, so the two can never drift apart.
- Unknown arguments are rejected (`additionalProperties: false`).
- Raise `ToolError("...")` to send a plain message back to the model.
- Sync functions run in a worker thread; `async def` tools are awaited.

Tool modules are listed in `ira.yaml` by dotted name or file path. A module can
define `setup(ctx)` (called after import, with `ctx.data_dir`) and `seed(ctx)`
(called by `ira demo seed`).

## Read tools and action tools

**Read tools** (`@tool`) run as soon as the model calls them.

**Action tools** (`@action`) change something, so calling one only creates a
**pending action**:

```python
def _summary(id: int) -> str:
    appointment = load(id)  # may raise ToolError("no such appointment")
    return f"Cancel appointment #{id}: {appointment.patient} on {appointment.when}"


@action(summary=_summary)
def cancel_appointment(id: int) -> dict:
    """Cancel an appointment."""
    ...
```

The `summary` is what the owner reads before confirming, so make it specific.
It can be a format string over the arguments or a function with the same
signature as the tool; a function can look records up and refuse the
proposal by raising `ToolError`.

A pending action stores the validated parameters, the summary and an expiry
(120 seconds by default). The model is told that nothing has happened yet.
The owner confirms with the PIN on the web card, over the API, or by typing it
in Telegram; then your function runs exactly once.

## The action PIN

- Set with `ira pin set`; 4 to 12 digits; stored as a salted PBKDF2 hash.
- Three wrong PINs in a row lock **all** actions for 15 minutes.
- A message consisting only of a PIN is never sent to a model, on any channel.
- Every proposal and every confirmation outcome (executed, failed, wrong PIN,
  locked, expired, cancelled, already done) is written to the audit log.

## Models, tiers and fallback

A **provider** is an endpoint plus its credentials: `openai` (any
OpenAI-compatible server), `anthropic`, `bedrock_mantle`, or `fake`.

A **tier** is an ordered list of `provider:model` references:

```yaml
tiers:
  default: [openai:gpt-4o-mini, bedrock:openai.gpt-oss-120b, demo:router]
```

Each call tries the models in order and moves on after an error, a timeout or
a capacity refusal (HTTP 429, 503, 529, "overloaded"). A model that failed
cools down for `cooldown_seconds` and is tried last until then, so one broken
model does not add its timeout to every request. When streaming, the gateway
can only fall back before the first word reaches the user; it never mixes
two models' answers.

Every request writes a row to the `calls` table: the model that answered, the
models tried, attempts, seconds, tokens and cost (from the `prices` table in
`ira.yaml`). Never a key or a prompt.

## Conversations

Each channel keeps conversations in SQLite. The model sees the last
`history_messages` messages, and the window always starts on a user turn,
because providers reject a tool result whose call was cut off. On Telegram,
`/new` starts fresh context; the transcript stays for the admin.

## Accounts, roles and tokens

| Role | Ask | Voice | Confirm actions | Admin read | Admin write | Users |
| --- | --- | --- | --- | --- | --- | --- |
| owner | yes | yes | yes | yes | yes | yes |
| admin | yes | yes | yes | yes | yes | |
| staff | yes | yes | yes | | | |
| viewer | | | | yes | | |

People sign in with email and password (a session). Programs use **API
tokens**, which belong to a user and carry scopes (`ask`, `voice`, `actions`,
`admin.read`) that can only narrow that user's role. A phone token with scope
`ask` can ask and nothing else.

## Channels

- **Web chat** at `/`: streamed answers, confirm cards, mic and speaker.
- **HTTP API** under `/v1`: the same features for your own apps.
- **Admin API** under `/v1/admin`: read-only views for dashboards.
- **Telegram**: a paired private chat; voice notes in, voice out.

## Voice

- **Speech to text**: an OpenAI-compatible chat model that accepts
  `input_audio` (`chat_audio`), or Whisper's `/audio/transcriptions`.
- **Text to speech**: Amazon Polly or OpenAI's `/audio/speech`.
- **Spoken text** is shortened first: markdown, tables, code and links are
  removed, and long answers are cut at a sentence with "Full details are in
  the text above."
