"""Patterns in one person's observations: plain arithmetic, so every number can be checked.

* **Times of day**, weekdays and weekends apart: when they reach or leave a
  named place, and when they start and stop using their Mac. One reading per
  day: the earliest arrival, the latest departure. A day runs from 04:00 to
  04:00, so working past midnight stays in the same day.
* **Durations**: leaving one place, then reaching another on the same day.
* **Answer preferences** from thumbs up and down: the language and the length
  of the answers the person liked.

Each pattern carries its evidence: the days, the median, the middle half
(first to third quartile), how many of the recent matching days it was seen,
and the observations behind it. The sentence is written from that evidence;
``numbers_ok`` refuses any sentence holding a number the evidence does not.
"""

from __future__ import annotations

import datetime as dt
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

DAY_START = 4 * 60  # minutes: a day runs from 04:00 to 04:00
WINDOW_DAYS = 21  # "seen on N of the last M weekdays" looks this far back
MIN_DAYS = 8
MIN_SPAN_DAYS = 14
MAX_SPREAD = 45  # minutes: the middle half of a routine time
MAX_DURATION_SPREAD = 30
MIN_FEEDBACK = 8
LANGUAGE_NAMES = {"hi": "Hindi", "hinglish": "Hinglish", "en": "English"}


@dataclass
class Pattern:
    kind: str  # time, duration, preference
    key: str
    text: str
    evidence: dict[str, Any]
    confidence: float
    passes: bool  # the evidence part of the proof gate (the person's yes is the other)
    observation_ids: list[int] = field(default_factory=list)


def clock(minutes: float) -> str:
    """Minutes after the 04:00 day start, as a wall-clock time: 870 -> 18:30."""
    total = int(round(minutes + DAY_START)) % 1440
    return f"{total // 60:02d}:{total % 60:02d}"


def quartiles(values: list[float]) -> tuple[float, float, float]:
    """(first quartile, median, third quartile), inclusive, as most people compute them."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0], ordered[0], ordered[0]
    q1, q2, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
    return q1, q2, q3


@dataclass
class Point:
    day: dt.date
    minutes: float  # after 04:00
    observation_id: int


def _local(at: float, zone: ZoneInfo) -> tuple[dt.date, float]:
    moment = dt.datetime.fromtimestamp(at, zone)
    minutes = moment.hour * 60 + moment.minute + moment.second / 60
    shifted = minutes - DAY_START
    day = moment.date()
    if shifted < 0:
        shifted += 1440
        day -= dt.timedelta(days=1)
    return day, shifted


def _weekday(day: dt.date) -> bool:
    return day.weekday() < 5


def daily_points(observations: list[dict[str, Any]], zone: ZoneInfo) -> dict[str, list[Point]]:
    """One point per day per routine: ``arrive:Office``, ``leave:Office``, ``first_activity``..."""
    days: dict[tuple[str, dt.date], Point] = {}

    def keep(key: str, day: dt.date, minutes: float, oid: int, earliest: bool) -> None:
        current = days.get((key, day))
        if current is None or (
            minutes < current.minutes if earliest else minutes > current.minutes
        ):
            days[(key, day)] = Point(day, minutes, oid)

    for obs in observations:
        day, minutes = _local(obs["at"], zone)
        kind, label, oid = obs["kind"], obs.get("label"), obs["id"]
        if kind == "arrive" and label:
            keep(f"arrive:{label}", day, minutes, oid, True)
        elif kind == "leave" and label:
            keep(f"leave:{label}", day, minutes, oid, False)
        elif kind == "first_activity":
            keep("first_activity", day, minutes, oid, True)
        if obs.get("source") == "mac":
            if label:  # first and last seen on a named network: reaching and leaving it
                keep(f"arrive:{label}", day, minutes, oid, True)
                keep(f"leave:{label}", day, minutes, oid, False)
            if kind in ("lock", "sleep"):
                keep("last_activity", day, minutes, oid, False)
    out: dict[str, list[Point]] = defaultdict(list)
    for (key, _), point in sorted(days.items(), key=lambda item: item[1].day):
        out[key].append(point)
    return out


def _routine_words(key: str) -> tuple[str, str]:
    """(what, the verb phrase) for a routine key."""
    if key.startswith("arrive:"):
        return "arrive", f"reach {key.split(':', 1)[1]}"
    if key.startswith("leave:"):
        return "leave", f"leave {key.split(':', 1)[1]}"
    if key == "first_activity":
        return "first_activity", "start on your Mac"
    return "last_activity", "stop using your Mac"


def time_patterns(
    observations: list[dict[str, Any]], zone: ZoneInfo, today: dt.date
) -> list[Pattern]:
    out = []
    for key, points in daily_points(observations, zone).items():
        for weekdays in (True, False):
            chosen = [p for p in points if _weekday(p.day) == weekdays]
            if len(chosen) < 2:
                continue
            q1, median, q3 = quartiles([p.minutes for p in chosen])
            spread = round(q3 - q1)
            span = (chosen[-1].day - chosen[0].day).days
            window = [
                today - dt.timedelta(days=n)
                for n in range(WINDOW_DAYS)
                if _weekday(today - dt.timedelta(days=n)) == weekdays
            ]
            seen = len({p.day for p in chosen} & set(window))
            days_word = "weekdays" if weekdays else "weekend days"
            _, verb = _routine_words(key)
            evidence = {
                "days": len(chosen),
                "first_day": chosen[0].day.isoformat(),
                "last_day": chosen[-1].day.isoformat(),
                "span_days": span,
                "median": clock(median),
                "q1": clock(q1),
                "q3": clock(q3),
                "spread_minutes": spread,
                "seen": seen,
                "window": len(window),
                "dates": [p.day.isoformat() for p in chosen],
                "times": [clock(p.minutes) for p in chosen],
            }
            text = (
                f"You {verb} at about {evidence['median']} on {days_word} "
                f"(most days between {evidence['q1']} and {evidence['q3']}; "
                f"seen on {seen} of the last {len(window)} {days_word})."
            )
            passes = len(chosen) >= MIN_DAYS and span >= MIN_SPAN_DAYS and spread <= MAX_SPREAD
            confidence = round(
                min(1.0, len(chosen) / 15) * max(0.0, 1 - spread / (2 * MAX_SPREAD)), 2
            )
            out.append(
                Pattern(
                    kind="time",
                    key=f"{key}:{'weekdays' if weekdays else 'weekends'}",
                    text=text,
                    evidence=evidence,
                    confidence=confidence,
                    passes=passes,
                    observation_ids=[p.observation_id for p in chosen],
                )
            )
    return out


def duration_patterns(observations: list[dict[str, Any]], zone: ZoneInfo) -> list[Pattern]:
    """Leaving one named place and reaching another the same day, within three hours."""
    points = daily_points(observations, zone)
    trips: dict[tuple[str, str], list[tuple[dt.date, float, list[int]]]] = defaultdict(list)
    leaves = {k.split(":", 1)[1]: v for k, v in points.items() if k.startswith("leave:")}
    arrives = {k.split(":", 1)[1]: v for k, v in points.items() if k.startswith("arrive:")}
    for start, start_points in leaves.items():
        for end, end_points in arrives.items():
            if start == end:
                continue
            by_day = {p.day: p for p in end_points}
            for leave in start_points:
                arrive = by_day.get(leave.day)
                if arrive and 0 < arrive.minutes - leave.minutes <= 180:
                    trips[(start, end)].append(
                        (
                            leave.day,
                            arrive.minutes - leave.minutes,
                            [leave.observation_id, arrive.observation_id],
                        )
                    )
    out = []
    for (start, end), rows in trips.items():
        if len(rows) < 2:
            continue
        q1, median, q3 = quartiles([r[1] for r in rows])
        spread = round(q3 - q1)
        span = (rows[-1][0] - rows[0][0]).days
        evidence = {
            "days": len(rows),
            "first_day": rows[0][0].isoformat(),
            "last_day": rows[-1][0].isoformat(),
            "span_days": span,
            "median_minutes": round(median),
            "q1_minutes": round(q1),
            "q3_minutes": round(q3),
            "spread_minutes": spread,
            "dates": [r[0].isoformat() for r in rows],
            "minutes": [round(r[1]) for r in rows],
        }
        text = (
            f"Going from {start} to {end} takes you about {evidence['median_minutes']} minutes "
            f"(between {evidence['q1_minutes']} and {evidence['q3_minutes']} on most of "
            f"{len(rows)} days)."
        )
        passes = len(rows) >= MIN_DAYS and span >= MIN_SPAN_DAYS and spread <= MAX_DURATION_SPREAD
        out.append(
            Pattern(
                kind="duration",
                key=f"duration:{start}:{end}",
                text=text,
                evidence=evidence,
                confidence=round(min(1.0, len(rows) / 15), 2),
                passes=passes,
                observation_ids=[oid for r in rows for oid in r[2]],
            )
        )
    return out


def preference_patterns(observations: list[dict[str, Any]], zone: ZoneInfo) -> list[Pattern]:
    feedback = [o for o in observations if o["kind"] == "feedback" and o.get("detail")]
    ups = [o for o in feedback if o["detail"].get("rating") == "up"]
    out = []
    if len(feedback) >= 2:
        first = _local(feedback[0]["at"], zone)[0]
        last = _local(feedback[-1]["at"], zone)[0]
        span = (last - first).days
    else:
        span = 0
    languages = defaultdict(int)
    for item in ups:
        languages[item["detail"].get("language")] += 1
    if ups:
        language, count = max(languages.items(), key=lambda kv: kv[1])
        if language in LANGUAGE_NAMES:
            evidence = {
                "liked": count,
                "thumbs_up": len(ups),
                "language": language,
                "span_days": span,
            }
            text = (
                f"You like answers in {LANGUAGE_NAMES[language]}: {count} of your "
                f"{len(ups)} thumbs up were for {LANGUAGE_NAMES[language]} answers."
            )
            passes = len(ups) >= MIN_FEEDBACK and count / len(ups) >= 0.7 and span >= MIN_SPAN_DAYS
            out.append(
                Pattern(
                    "preference",
                    "preference:language",
                    text,
                    evidence,
                    round(count / len(ups), 2),
                    passes,
                    [o["id"] for o in ups],
                )
            )
    downs = [o for o in feedback if o["detail"].get("rating") == "down"]
    up_chars = [o["detail"].get("chars") for o in ups if isinstance(o["detail"].get("chars"), int)]
    down_chars = [
        o["detail"].get("chars") for o in downs if isinstance(o["detail"].get("chars"), int)
    ]
    if len(up_chars) >= 2 and len(down_chars) >= 2:
        liked = round(statistics.median(up_chars))
        disliked = round(statistics.median(down_chars))
        shorter = liked * 2 <= disliked
        longer = disliked * 2 <= liked
        if shorter or longer:
            word = "short" if shorter else "longer"
            evidence = {
                "liked_chars": liked,
                "disliked_chars": disliked,
                "thumbs_up": len(up_chars),
                "thumbs_down": len(down_chars),
                "span_days": span,
            }
            text = (
                f"You like {word} answers: your thumbs up went to answers of about {liked} "
                f"characters, your thumbs down to about {disliked}."
            )
            passes = len(up_chars) + len(down_chars) >= MIN_FEEDBACK and span >= MIN_SPAN_DAYS
            out.append(
                Pattern(
                    "preference",
                    "preference:length",
                    text,
                    evidence,
                    0.7,
                    passes,
                    [o["id"] for o in ups + downs],
                )
            )
    return out


def find_patterns(
    observations: list[dict[str, Any]], zone: ZoneInfo, today: dt.date
) -> list[Pattern]:
    return (
        time_patterns(observations, zone, today)
        + duration_patterns(observations, zone)
        + preference_patterns(observations, zone)
    )


_NUMBER = re.compile(r"\d+(?::\d+)?")


def _flatten(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(_flatten(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_flatten(v) for v in value)) if value else set()
    return {str(value)}


def numbers_ok(text: str, evidence: dict[str, Any]) -> bool:
    """Every number in a learning's sentence is one of its evidence's values."""
    known = _flatten(evidence)
    return all(number in known for number in _NUMBER.findall(text))
