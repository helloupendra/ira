# Contributing to IRA

Thanks for helping. IRA is small on purpose: a change should keep it easy to
read in an afternoon.

## Set up

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,aws,ogg]"
pre-commit install
```

Before your first commit:

1. **Use a no-reply commit address.** The `ira-identity` hook refuses any
   other, because every commit publishes its author email:

   ```bash
   git config user.email "<id>+<username>@users.noreply.github.com"
   ```

2. **Create your private deny-list** (optional but recommended). It lives
   outside the repository, so its contents can never be committed:

   ```bash
   mkdir -p ~/.config/ira
   $EDITOR ~/.config/ira/denylist.txt
   ```

   One entry per line: a literal (matched case-insensitively) or `re:` and a
   regular expression. Lines starting with `#` are comments. Put in anything
   that must never be published: your company's internal names, hostnames,
   account numbers, real customer names. Use `IRA_DENYLIST` to point
   somewhere else.

## Check your work

```bash
ruff check . && ruff format --check .
pytest
pre-commit run --all-files
python scripts/check_denylist.py --all
```

Tests use fakes only: `ScriptedProvider` and `RouterProvider` for models,
`FakeSTT`/`FakeTTS` for voice, `httpx.MockTransport` for wire formats, and a
fake Bot API for Telegram. A test must never need a key or the network.

## Style

- Python 3.11+, typed, formatted by ruff (line length 100).
- Comments explain *why*. The code already says *what*.
- Prefer the standard library; a new dependency needs a reason in the PR.
  Optional integrations (AWS, OGG decoding) go behind an extra.
- Demo and test data are fictional: `example.com`, 555-01xx numbers, made-up
  names.

## Commits and pull requests

- Small, focused commits with short imperative messages: "Add Whisper
  speech-to-text", "Fix stream fallback after first token".
- Describe what changed and how you tested it in the PR.
- Never commit secrets, `.env` files, databases or logs. If you do by
  mistake, say so at once: rotating the secret matters more than rewriting
  history.
