# Sunrise Dental Clinic

A complete, fictional example: a small dental practice whose receptionist
assistant can look up opening hours and free slots, find a patient's
appointments, and book or cancel them after the owner confirms with a PIN.

Everything is made up: the clinic, the street, the patients, the 555-01xx
phone numbers and the `example.com` email addresses.

| File | What it is |
| --- | --- |
| `clinic.py` | The tools, plus `setup(ctx)` and `seed(ctx)` hooks |
| `ira.yaml` | Config that runs with no API key |
| `data/` | Created by `ira demo seed`; gitignored |

## The tools

| Tool | Kind | What it does |
| --- | --- | --- |
| `clinic_hours()` | read | Opening hours, phone and address |
| `find_slots(date)` | read | Free 30-minute slots on a day (`YYYY-MM-DD`, `today`, `tomorrow`) |
| `list_appointments(name)` | read | Upcoming appointments for a patient (partial names match) |
| `book_appointment(name, slot)` | action | Books a free slot, after the PIN |
| `cancel_appointment(id)` | action | Cancels an appointment, after the PIN |

The action summaries do real work: `cancel_appointment`'s summary looks the
appointment up, so the owner confirms "Cancel appointment #3: Riley Demo on
Tuesday 13 October at 15:00", not "cancel_appointment(id=3)". It also refuses
to propose cancelling an appointment that does not exist. Booking checks the
slot when proposing and again when running, because it may have gone in
between.

## Run it with no API key

From the repository root, with IRA installed (`pip install -e .`):

```bash
cd examples/clinic
ira demo seed          # a week of fictional appointments
ira setup              # owner email and password
ira pin set            # e.g. 4 to 12 digits
ira serve              # http://127.0.0.1:8765
```

Sign in at <http://127.0.0.1:8765> and try:

```text
what are the clinic hours?
find slots tomorrow
show appointments for Avery
book name="Jamie Example" slot="2026-10-14 10:00"
cancel appointment 3
```

Use a date from `find slots` for the booking. Actions show a card: type the
PIN to run it, or Cancel. Try a wrong PIN three times to see the lock.

The `demo` provider is a keyword router, not a language model. It picks a tool
by matching words from the tool names and pulls arguments out with simple
patterns, which is enough to show the whole flow (tools, proposals, PIN,
audit, voice pipeline) without a key. The demo speech-to-text returns a fixed
sentence; replies are spoken with the browser's own voice.

## Run it with a real model

Edit `ira.yaml`: add a provider and put it first in the tier, keeping the
router as a last resort.

```yaml
models:
  providers:
    openai:
      type: openai
      api_key_env: OPENAI_API_KEY
    demo:
      type: fake
  tiers:
    default: [openai:gpt-4o-mini, demo:router]
  prices:
    openai:gpt-4o-mini: { input: 0.15, output: 0.60 }   # check current prices
```

Then put the key in the environment or in `examples/clinic/.env` (gitignored):

```bash
echo 'OPENAI_API_KEY=...' > .env
ira serve
```

Now you can ask normally: "Can Jordan Sample come in on Thursday morning?",
"Cancel Avery's next appointment". The model looks up slots and appointments,
proposes the change, and waits for the PIN.

Other providers work the same way. A local OpenAI-compatible server:

```yaml
    local: { type: openai, base_url: "http://127.0.0.1:11434/v1" }
```

Amazon Bedrock (Mantle endpoint, signed with your AWS role or profile;
`pip install -e ".[aws]"`):

```yaml
    bedrock: { type: bedrock_mantle, region: us-east-1 }
```

## Real voice

Replace the fake speech settings with real ones, for example:

```yaml
voice:
  stt: { type: whisper, provider: openai, model: whisper-1 }
  tts: { type: openai, provider: openai, model: tts-1, voice: alloy }
```

## Make it yours

Copy this folder, rename the tools, and point them at your own data: a
booking system's API, a spreadsheet export, a shop database. Keep reads as
`@tool` and anything that changes data as `@action` with a specific summary.
