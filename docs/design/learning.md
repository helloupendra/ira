# Design note: Ira learns your routines (section 6b)

A person can let their own Ira notice how their day goes (when they reach
the office, when they leave, how long the commute takes, how they like to be
answered) and use it, but only what they agreed to, with the evidence shown,
and only after they said yes. Everything is per person, off by default, and
deletable.

## Observations

`observations`: one row per thing noticed, for one person.

| Field | Holds |
| --- | --- |
| `kind` | `lock`, `unlock`, `sleep`, `wake`, `first_activity`, `network`, `arrive`, `leave`, `said`, `feedback` |
| `label` | a name the person chose: "Office", "Home". Never a network name, never coordinates |
| `source` | `mac`, `phone`, `conversation`, `app` |
| `at`, `device_id`, `detail` | when; which device; a little JSON (a quote, a rating) |

Kept 90 days by default (`learning_days`, per person). Nothing is recorded
unless learning is on for the person **and** that source is on.

### Sources, each switched on by the person

- **Mac routine**: a new device skill, `routine`, switched on with the PIN
  like any grant. The companion then sends `observe` frames: lock and
  unlock, sleep and wake, the first activity of the day, and a change of
  network. It reads the screen lock from CoreGraphics, sleep from gaps in
  its own clock, idle time from IOKit, and identifies a network by a salted
  hash of the default gateway's hardware address: the salt stays on the Mac,
  so the server can only tell networks apart. The person names a network
  once ("the network Studio Mac is on now is Office"); unnamed networks are
  never used for patterns. The server tells the companion when the skill
  changes (`{"type": "skills"}`), so it observes nothing while it is off.
- **Phone places**: an iOS Shortcuts personal automation ("When I arrive at
  Office") posts `{"event": "arrive", "place": "Office"}` to
  `POST /v1/observations` with an API token whose only scope is `observe`.
  The person makes that token on their **What Ira knows** page (a new grant,
  so with the PIN). Only the place label is stored; a body with coordinates
  is refused. Android does the same later.
- **What you say**: after a turn, when the message mentions leaving,
  reaching or going somewhere ("main office nikal raha hoon"), the fast
  model tier extracts `{kind, place, quote}`. The **quote check** keeps it
  only if the quote is the person's own words, word for word, and the place
  is in the quote or is a label they already use.
- **Feedback**: thumbs up or down on an answer, with an optional correction.
  It records the answer's language and length, never its text.

## Learner

Nightly (at 03:00 server time) and on demand. Pure functions over one
person's observations, so every number can be checked:

- **Times of day** per (kind, label), weekdays and weekends apart: the
  median, the middle half (first to third quartile), and "seen on N of the
  last M weekdays".
- **Durations**: leave A then arrive B on the same day ("commute about 35
  min"), median and middle half.
- **Answer preferences** from feedback: reply language and length that get
  thumbs up.
- **Sequences** (after reaching Office, the first thing asked of Ira) come
  later; they need more sources.

Each pattern is a **learning**: `kind`, a stable `key`
(`leave:Office:weekdays`), a sentence, its evidence (count, days, dates,
median, quartiles) and a confidence. The sentence is filled in by code from
the evidence: no model writes it, and a check refuses any sentence holding a
number that is not in its evidence.

## The proof gate

- A learning is **proposed** until it has at least 8 observations over at
  least 14 days with a middle half no wider than 45 minutes.
- Then Ira **asks once**, in plain words, in the app and on Telegram: "I
  noticed you leave Office around 18:34 on weekdays (12 of the last 15).
  Shall I remember that?" Yes makes it **active**; no makes it
  **rejected**, and it is not asked again.
- An active learning not seen for 21 days **fades**. One whose recent
  median moves outside its old middle half is proposed again with the new
  numbers.

## Use

- Active learnings go into the person's system prompt, at most 8 lines and
  600 characters, marked as things they approved.
- **Nudges** (off until the person switches them on): 15 minutes before a
  routine time on a matching day, unless it already happened ("18:19: you
  usually leave Office at about 18:34").
- **Reminders**: a Tier 1 tool, `remind_me`, at a time ("kal subah 9 baje
  yaad dilana") or on a place event ("remind me when I reach the office").
  Due reminders reach the person's channels like device events.

## What Ira knows about you

A page in the Ira app and the console, for one's own learnings only:

- each learning with its evidence and a small dot plot of the times;
- approve, reject, edit the label, forget (the learning and its
  observations);
- the sources with their switches, network names, the phone token and the
  Shortcut steps, the retention days, pause learning;
- export and delete everything learned (also part of "Your data").

Admins never see another person's observations or learnings.

## Tests

The pattern finder on fixed observation sets against hand-computed medians
and quartiles; the proof gate's thresholds; per-person isolation; refusing
coordinates; the quote check; the "no invented number" check on sentences;
fading; the companion's observers with fake clocks and fake system readings.
