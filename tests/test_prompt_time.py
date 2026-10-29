"""The model is told the real time in the person's zone, so it never guesses it."""

from __future__ import annotations

import datetime as dt

from .conftest import make_runtime


def test_the_prompt_says_the_time_in_the_persons_zone():
    runtime = make_runtime()
    owner = runtime.accounts.create_user("owner@example.com", "a-long-password-here", "owner")
    runtime.assistant.user_settings.set(owner.id, "timezone", "Asia/Kolkata")
    # 18:24 UTC on 29 Oct 2026 is 23:54 in India.
    runtime.assistant.clock = lambda: dt.datetime(2026, 10, 29, 18, 24, tzinfo=dt.UTC).timestamp()
    prompt = runtime.assistant.system_prompt(owner.id)
    assert "Today is Thursday 29 October 2026 (2026-10-29)." in prompt
    assert "It is now 23:54 (11:54 PM), Asia/Kolkata" in prompt

    # Just past midnight there, it is already the next day.
    runtime.assistant.clock = lambda: dt.datetime(2026, 10, 29, 18, 31, tzinfo=dt.UTC).timestamp()
    assert "Today is Friday 30 October 2026" in runtime.assistant.system_prompt(owner.id)
