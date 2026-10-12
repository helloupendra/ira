from __future__ import annotations

from ira.voice.shorten import CUT_NOTE, speakable, strip_markdown


def test_markdown_tables_code_and_links_are_removed():
    text = """# Your week

**Tuesday** is busy. See [the calendar](https://calendar.example.com/x) for more.

| Day | Slots |
|-----|-------|
| Tue | 3     |

```python
print("never read aloud")
```

- First item
- Second item
Visit https://example.com/page today."""
    spoken = strip_markdown(text)

    assert spoken == (
        "Your week. Tuesday is busy. See the calendar for more. "
        "First item. Second item. Visit today."
    )
    for gone in ("|", "#", "**", "http", "print", "```"):
        assert gone not in spoken


def test_snake_case_names_survive():
    assert strip_markdown("Use find_slots and clinic_hours.") == "Use find_slots and clinic_hours."


def test_short_text_is_unchanged():
    assert speakable("Your appointment is at 9:30.") == "Your appointment is at 9:30."


def test_long_text_is_cut_at_a_sentence_with_a_note():
    sentence = "The clinic has a free slot at nine thirty on Tuesday morning. "
    spoken = speakable(sentence * 20, max_chars=200)

    assert spoken.endswith(CUT_NOTE)
    body = spoken[: -len(CUT_NOTE)].strip()
    assert body.endswith(".")
    assert len(body) <= 200
    assert body.count("Tuesday morning.") == 3


def test_text_without_sentence_breaks_is_cut_at_a_word():
    spoken = speakable("word " * 200, max_chars=50)
    assert spoken.endswith(CUT_NOTE)
    assert spoken.startswith("word word")
    assert "wor." not in spoken


def test_note_is_not_added_when_nothing_was_cut():
    assert CUT_NOTE not in speakable("Short answer.", max_chars=400)
