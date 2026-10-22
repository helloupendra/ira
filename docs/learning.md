# What Ira learns about you

Ira can learn your routine: when you usually leave the office, how long the
drive home takes, whether you like short answers. It is **off** until you
switch it on, it notices only what you choose, and it remembers nothing
until you say yes.

Everything here is in the Ira app: menu, **What Ira knows about you**.

## Switch it on

1. Open **What Ira knows about you**.
2. Tick **Let Ira learn my routine**, and choose where from:
    - **My phone**, when an iPhone Shortcut says you reached or left a
      place you named (steps below);
    - **What I tell Ira** about where you are going ("office se nikal raha
      hoon");
    - **My thumbs** on Ira's answers.
3. Choose how long Ira keeps what it noticed (30 to 365 days; 90 by
   default). Older notes are deleted every day.
4. Type your PIN and **Save**. Switching anything on needs your PIN;
   switching it off never does.

A **Mac** is switched on separately, under **Your devices**: its *routine*
skill. With it on, the Mac tells Ira when it locks, unlocks, sleeps and
wakes, and which network it is on, as a code only (see
[the Mac companion](clients/mac.md#its-routine)).

## Name your places

With a Mac's routine on, the networks it joins appear under **Places** as
codes, such as `3f9a2c1b`. Ira never learns a network's name or where it
is. Give the ones you care about a name, such as **Office** or **Home**;
from then on, the Mac on that network counts as being at that place. An
iPhone Shortcut uses the same names.

## What Ira looks for, and when it asks

Every night, after 3 a.m. in your time zone (or when you tap **Look for
patterns now**), Ira looks at what it noticed and finds:

- **routine times**: when you reach or leave a place, start or stop on your
  Mac, on weekdays and at weekends apart;
- **how long a trip takes**, from leaving one place to reaching another;
- **how you like answers**: in which language, and short or long, from your
  thumbs.

Each is written as a sentence from the numbers it saw, for example:

> You leave Office at about 18:34 on weekdays (most days between 18:25 and
> 18:45; seen on 9 of the last 15 weekdays).

The time is the middle one of the days it saw; "most days between" is the
middle half of them. Every number in the sentence comes from what Ira
noticed, and a sentence with any other number is refused.

Ira asks only when the evidence is strong: **at least 8 days, over at least
two weeks, with the middle half within 45 minutes**. Until then the pattern
shows as *still checking*.

Then it asks you, **once**, in the chat (and in Telegram, if you paired a
chat): "Shall I remember this?"

- **Yes, remember**: it is remembered. Ira uses it when it helps ("You
  usually leave at 18:34; it's 18:20").
- **No**: it is never asked again.
- **Reword** it in your own words, as long as its numbers stay the ones Ira
  saw.
- **Forget it**: the sentence and everything Ira noticed for it are
  deleted.

A remembered routine **fades** when it is not seen for three weeks, and Ira
asks again when it **changes** (your last five days all fall outside its
middle half).

At most 8 remembered sentences, 600 characters in all, go into what Ira
reads before answering you.

## Reminders and nudges

Ask in your own words:

- "kal subah 9 baje yaad dilana, bank ko call karna"
- "remind me to water the plants when I reach Office"
- "जब मैं ऑफिस से निकलूँ तो याद दिलाना कि दूध लेना है"

A reminder at a place needs a place you named. **Reminders** in the panel
lists them; cancel any.

**Nudges** (off by default): 15 minutes before a routine you approved, on a
day it has not happened yet, Ira says so. "18:20: you usually leave Office
at about 18:34."

## Your time zone

Routines and reminders use your own time zone. The Ira app sets it from
your browser the first time you open it; change it with
`PATCH /v1/me/settings` and `{"timezone": "Asia/Kolkata"}`.

## An iPhone Shortcut for places

The iPhone tells Ira when you reach or leave a place. It uses a key that
can do nothing else: not read your conversations, not ask Ira anything.

1. In **What Ira knows about you**, under **Your iPhone**, type your PIN and
   tap **Make a key for Shortcuts**. Copy the key and the address. They are
   shown once.
2. On the iPhone, open **Shortcuts**, then **Automation**, then **+**
   (New Automation).
3. Choose **Arrive**, pick the place (your office, say), and choose **Run
   Immediately**. Tap **Next**, then **New Blank Automation**.
4. Add the action **Get Contents of URL**. Paste the address. Tap the
   arrow to show more:
    - **Method**: POST;
    - **Headers**: add `Authorization` with the value `Bearer `
      followed by the key;
    - **Request Body**: JSON, with two text fields: `event` = `arrive`
      and `place` = the name you use in Ira, such as `Office`.
5. Tap **Done**. Make a second automation with **Leave** and `event` =
   `leave`.

Labels differ a little between iOS versions. The place name in the body is
all Ira receives: never coordinates, never an address. If learning or the
phone source is off, the iPhone's message is accepted and dropped.

To stop it, delete the automations, or tap **Revoke** under **Your iPhone**.

## What is kept, and for how long

| What | For how long |
| --- | --- |
| What Ira noticed: the kind (left, reached, locked...), the time, the place name you gave, the device | as long as you chose: 30 to 365 days |
| Remembered sentences, with their numbers | until you forget them or delete your data |
| Reminders | until they go off or you cancel them |
| Your thumbs: up or down, the answer's language and length, and your note | as long as you chose, like everything noticed |

Nobody else sees any of it: not an owner, not an admin. **Your data** in
the menu exports all of it, and **Delete my data** deletes it with the rest
of your data. See [Privacy](privacy.md).
