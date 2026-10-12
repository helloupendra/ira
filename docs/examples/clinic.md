# Example: Sunrise Dental Clinic

`examples/clinic/` in the repository is a complete, fictional receptionist
assistant for a small dental practice. It runs with no API key, and it is the
quickest way to see every part of IRA working together: read tools, action
proposals, the PIN, the audit log, voice, and the admin API.

Everything in it is invented: the clinic, its street, the patients, the
555-01xx phone numbers and the `example.com` addresses.

## Run it

```bash
cd examples/clinic
ira demo seed      # a week of fictional appointments in ./data/clinic.db
ira setup          # owner account
ira pin set        # action PIN
ira serve          # http://127.0.0.1:8765
```

Then ask `find slots tomorrow`, `show appointments for Avery` or
`cancel appointment 3`, and confirm the last one with the PIN.

## How it is built

### Configuration

`ira.yaml` names the tool file and uses the keyword-routing demo provider:

```yaml
tools:
  - ./clinic.py
models:
  providers:
    demo: { type: fake }
  tiers:
    default: [demo:router]
```

### Setup and seed hooks

IRA calls `setup(ctx)` after importing the module, and `ira demo seed` calls
`seed(ctx)`. The clinic uses them to find, and fill, its own SQLite file:

```python
def setup(ctx: ToolContext) -> None:
    global _db_path
    _db_path = ctx.data_dir / "clinic.db"
```

### A read tool

```python
@tool
def find_slots(
    date: Annotated[str, Field(description="Day to search: YYYY-MM-DD, 'today' or 'tomorrow'")],
) -> dict:
    """Free 30-minute appointment slots on one day."""
```

The docstring's first line and the `Field` description are what the model
sees; the same annotation validates the argument before the function runs.
Bad input raises `ToolError("use a date like 2026-10-14 ...")`, which goes
back to the model as a plain message it can act on.

### An action with a useful summary

```python
def _cancel_summary(id: int) -> str:
    row = ...  # look the appointment up
    if row is None:
        raise ToolError(f"there is no appointment #{id}")
    return f"Cancel appointment #{id}: {row['patient']} on {_spoken(when)}"


@action(summary=_cancel_summary)
def cancel_appointment(id: Annotated[int, Field(ge=1)]) -> dict:
    """Cancel an appointment. Ira only proposes it; it runs after the owner's PIN."""
```

The summary is what the owner reads on the confirm card, so it names the
patient and the time instead of an id. Because it can raise `ToolError`, an
impossible request (an unknown appointment, a taken slot) is refused before
anyone is asked for a PIN. `book_appointment` checks the slot again when it
runs, since it may have been taken in the two minutes the proposal was open.

## Switching to a real model

Add a provider in front of the router; see
[Getting started](../getting-started.md#use-a-real-model). With a real model
the same tools handle natural requests such as "Can Jordan Sample come in on
Thursday morning?" without any change to `clinic.py`.

## Tests

`tests/test_clinic_example.py` seeds a temporary copy, exercises each tool,
checks that the demo data is fictional, and runs a full proposal and PIN
confirmation through the demo router.
