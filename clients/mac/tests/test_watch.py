"""Progress readings, and the rules that end a watch."""

from __future__ import annotations

from ira_mac.watch import Watch, check, progress_of, summary


def page(text="", title="Upload", **progress):
    return {"title": title, "text": text, "progress": progress}


def test_progress_prefers_bars_then_steps_then_text():
    reading = progress_of({"bars": [{"percent": 63}], "percents": [10], "eta": ["4 min"]})
    assert (reading.percent, reading.eta) == (63, "4 min")
    assert summary("Upload", reading) == "Upload: 63%, about 4 min left"
    steps = progress_of({"counts": [{"done": 4, "total": 5}], "status": ["Done", "noise"]})
    assert (steps.percent, steps.step, steps.status) == (80, (4, 5), ("done",))
    assert summary("CI", steps) == "CI: 80%, step 4 of 5, Done"
    assert progress_of({"percents": [250, 42]}).percent == 42
    assert summary("Mail", progress_of({})) == "Mail: no progress shown"


def watch(**kwargs) -> Watch:
    w = Watch(id="w1", tab_id=2, title="Upload", started=0.0, **kwargs)
    w.start(page("63% uploading", bars=[{"percent": 63}], status=["error"]), 0.0)
    return w


def test_it_ends_at_100_percent():
    w = watch()
    assert check(w, page("70%", bars=[{"percent": 70}]), 10) is None
    done = check(w, page("done", bars=[{"percent": 100}]), 20)
    assert (done.reason, done.title, done.text) == (
        "complete",
        "Upload is done",
        "It reached 100%.",
    )


def test_it_ends_when_the_text_appears():
    done = check(watch(until_text="Upload complete"), page("All good. upload COMPLETE."), 5)
    assert done.reason == "text"


def test_a_new_status_word_ends_it_but_one_already_there_does_not():
    w = watch()
    assert check(w, page("an error banner from before", status=["error"]), 5) is None
    done = check(w, page("it failed", status=["error", "failed"]), 10)
    assert (done.reason, done.title) == ("status", "Upload failed")
    done = check(watch(), page("ok", status=["completed"]), 10)
    assert done.title == "Upload finished"


def test_idle_closed_and_timeout():
    w = watch(idle_seconds=30)
    assert check(w, page("same"), 10) is None  # changed just now
    assert check(w, page("same"), 35) is None
    done = check(w, page("same"), 41)
    assert done.reason == "idle" and "31 seconds" in done.text
    assert check(watch(), None, 5).reason == "closed"
    w = watch(timeout_minutes=1)
    done = check(w, page("70%", bars=[{"percent": 70}]), 61)
    assert done.reason == "timeout" and "Last seen: 70%." in done.text


def test_limits_on_the_rules():
    w = Watch(id="w", tab_id=1, title="x", idle_seconds=1, timeout_minutes=99999)
    assert w.idle_seconds == 10 and w.timeout_minutes == 1440
    assert "the tab closes" in w.describe()
