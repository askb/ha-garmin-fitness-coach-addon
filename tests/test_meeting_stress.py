#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
"""Self-check for meeting_stress: baseline math + ridge de-confounding.

Run: python -m pytest tests/test_meeting_stress.py   (or: python tests/test_meeting_stress.py)
"""

import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "pulsecoach"
    / "rootfs"
    / "app"
    / "scripts"
    / "meeting-stress.py"
)
_spec = importlib.util.spec_from_file_location("meeting_stress", _SCRIPT)
ms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ms)

_GCAL = _SCRIPT.with_name("gcal.py")
_gspec = importlib.util.spec_from_file_location("gcal", _GCAL)
gcal = importlib.util.module_from_spec(_gspec)
_gspec.loader.exec_module(gcal)

DAY = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _build():
    """alice = true +10 stressor; bob = 0 bystander who co-attends alice; carol = -6 calming.

    bob also gets solo-ish neutral meetings so ridge can separate him from alice.
    """
    lift = {"alice": 10.0, "bob": 0.0, "carol": -6.0, "dave": 0.0}
    # (day_offset, hour, [attendees])
    specs = [
        (0, 9, ["alice", "bob", "dave"]),
        (0, 14, ["alice", "dave"]),
        (1, 9, ["alice", "bob"]),
        (1, 14, ["bob", "dave"]),  # bob without alice -> neutral
        (2, 9, ["alice", "bob", "carol"]),
        (2, 14, ["bob", "dave"]),  # bob without alice -> neutral
        (3, 9, ["alice", "carol"]),
        (3, 14, ["carol", "dave"]),  # carol calming, no alice
        (4, 9, ["alice", "bob", "dave"]),
        (4, 14, ["carol", "bob"]),
    ]
    events, windows = [], []
    for d, h, att in specs:
        start = DAY.replace(hour=h) + timedelta(days=d)
        end = start + timedelta(minutes=40)
        events.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "title": "m",
                "attendees": att,
            }
        )
        windows.append(
            (int(start.timestamp()), int(end.timestamp()), sum(lift[a] for a in att))
        )

    # 2-min HR backbone at 62 bpm across each meeting day, with meeting lifts applied.
    series = []
    for d in range(5):
        day_start = int((DAY.replace(hour=7) + timedelta(days=d)).timestamp())
        for k in range(0, 11 * 60, 2):
            ts = day_start + k * 60
            bpm = 62.0 + sum(l for s, e, l in windows if s <= ts < e)
            series.append((ts, bpm))
    series.sort()
    return events, series


def test_ridge_deconfounds_bystander():
    events, series = _build()
    rows = ms.score_meetings(events, series)
    people = {p["attendee"]: p for p in ms.leaderboard(rows, lam=1.0)}

    # 1. alice is the clear top stressor.
    assert people["alice"]["ridge"] > 4.0, people["alice"]
    top = max(people.values(), key=lambda p: p["ridge"])["attendee"]
    assert top == "alice", top

    # 2. bob's NAIVE average is inflated by co-attending alice, but ridge clears him.
    assert people["bob"]["naive"] > 2.0, people["bob"]  # confounded
    assert abs(people["bob"]["ridge"]) < 2.5, people["bob"]  # de-confounded ~0
    assert people["bob"]["naive"] - people["bob"]["ridge"] > 1.5, people["bob"]

    # 3. carol reads as calming (negative effect).
    assert people["carol"]["ridge"] < -1.0, people["carol"]


def test_solo_and_oversize_meetings_skipped():
    events = [
        {
            "start": DAY.replace(hour=9).isoformat(),
            "end": DAY.replace(hour=9, minute=30).isoformat(),
            "title": "solo",
            "attendees": [],
        },
        {
            "start": DAY.replace(hour=10).isoformat(),
            "end": DAY.replace(hour=10, minute=30).isoformat(),
            "title": "townhall",
            "attendees": [f"p{i}" for i in range(20)],
        },
    ]
    series = [
        (int(DAY.replace(hour=7).timestamp()) + k * 60, 62.0) for k in range(0, 600, 2)
    ]
    assert ms.score_meetings(events, series) == []


def test_gcal_item_mapping():
    item = {
        "summary": "planning",
        "start": {"dateTime": "2026-07-01T09:00:00+10:00"},
        "end": {"dateTime": "2026-07-01T09:30:00+10:00"},
        "attendees": [
            {"displayName": "Alice", "email": "alice@x.org"},
            {"email": "bob@x.org", "responseStatus": "declined"},
            {"email": "room-3@resource.calendar.google.com", "resource": True},
            {"email": "me@x.org", "self": True},
            {"email": "carol@x.org"},
        ],
    }
    ev = gcal._item_to_event(item)
    assert ev["attendees"] == ["Alice", "carol"], ev
    # all-day events (date, no dateTime) are dropped
    assert (
        gcal._item_to_event(
            {"start": {"date": "2026-07-01"}, "end": {"date": "2026-07-02"}}
        )
        is None
    )


def test_gcal_fetch_multi_calendar_dedup(monkeypatch):
    """fetch_events() merges selected calendars and dedups by (iCalUID, start)."""

    def _item(uid, hour, title, who):
        return {
            "iCalUID": uid,
            "summary": title,
            "start": {"dateTime": f"2026-07-01T{hour:02d}:00:00+10:00"},
            "end": {"dateTime": f"2026-07-01T{hour:02d}:30:00+10:00"},
            "attendees": [{"email": f"{who}@x.org"}],
        }

    # Same meeting (uid-shared) appears on both calendars; each also has a
    # unique meeting. Dedup must keep the shared one exactly once → 3 total.
    per_cal = {
        "primary": [
            _item("uid-shared", 9, "standup", "alice"),
            _item("uid-a", 10, "1:1", "bob"),
        ],
        "team@x.org": [
            _item("uid-shared", 9, "standup", "alice"),
            _item("uid-b", 11, "review", "carol"),
        ],
    }
    monkeypatch.setattr(gcal, "load_token", lambda: {"ok": True})
    monkeypatch.setattr(gcal, "_refresh_access_token", lambda tok: "access")
    monkeypatch.setattr(
        gcal, "selected_calendar_ids", lambda: ["primary", "team@x.org"]
    )
    monkeypatch.setattr(
        gcal, "_list_events_for_calendar", lambda access, cid, days: per_cal[cid]
    )

    events = gcal.fetch_events(14)
    titles = sorted(e["title"] for e in events)
    assert titles == ["1:1", "review", "standup"], titles

    # Recurring series: two occurrences share one iCalUID (singleEvents=true)
    # but differ by start — they must NOT be de-duplicated into one.
    rec = [
        _item("uid-rec", 9, "weekly", "alice"),
        {
            **_item("uid-rec", 9, "weekly", "alice"),
            "start": {"dateTime": "2026-07-08T09:00:00+10:00"},
            "end": {"dateTime": "2026-07-08T09:30:00+10:00"},
        },
    ]
    monkeypatch.setattr(gcal, "selected_calendar_ids", lambda: ["primary"])
    monkeypatch.setattr(
        gcal, "_list_events_for_calendar", lambda access, cid, days: rec
    )
    assert len(gcal.fetch_events(14)) == 2


def test_interactions_jsonl():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "interactions.jsonl"
        path.write_text(
            '{"person": "Mum", "minutes": 45, "end": "2026-07-01T18:00:00+10:00"}\n'
            "not json at all\n"
            '{"person": "", "minutes": 30, "end": "2026-07-01T19:00:00+10:00"}\n'
            '{"person": "Dave", "minutes": 0, "end": "2026-07-01T20:00:00+10:00"}\n'
        )
        evs = ms.load_interactions(str(path))
    assert len(evs) == 1, evs
    ev = evs[0]
    assert ev["attendees"] == ["Mum"]
    assert ms.parse_ts(ev["end"]) - ms.parse_ts(ev["start"]) == 45 * 60
    # missing file -> empty, no crash
    assert ms.load_interactions("/nonexistent/interactions.jsonl") == []


def test_skipped_reports_no_hr_interactions():
    """Interactions with no HR coverage are dropped but reported, not silent."""
    # One scorable calendar meeting (has surrounding HR) + one interaction that
    # falls entirely outside the HR series (as when logged before today synced).
    meet_start = DAY.replace(hour=9)
    meet_end = meet_start + timedelta(minutes=40)
    inter_start = DAY.replace(hour=20)  # after the series ends -> no HR
    inter_end = inter_start + timedelta(minutes=30)
    events = [
        {
            "start": meet_start.isoformat(),
            "end": meet_end.isoformat(),
            "title": "standup",
            "attendees": ["alice", "bob"],
        },
        {
            "start": inter_start.isoformat(),
            "end": inter_end.isoformat(),
            "title": "interaction: Mum",
            "attendees": ["Mum"],
        },
    ]
    # 07:00 -> 11:00 HR backbone (covers the meeting, not the evening interaction).
    day7 = int(DAY.replace(hour=7).timestamp())
    series = [(day7 + k * 60, 62.0) for k in range(0, 4 * 60, 2)]

    skipped: list[dict] = []
    rows = ms.score_meetings(events, series, skipped=skipped)
    # meeting scored, interaction dropped for no HR.
    assert len(rows) == 1 and rows[0]["title"] == "standup", rows
    reasons = [s["reason"] for s in skipped]
    assert "no_hr" in reasons, skipped

    summary = ms.summarize_skipped(skipped)
    assert summary["no_hr"] == 1, summary
    assert summary["interactions_no_hr"] == 1, summary
    assert "Mum" in summary["no_hr_titles"], summary  # prefix stripped


def test_thin_baseline_is_distinct_from_no_hr():
    """A meeting with HR but too little surrounding quiet time is thin_baseline,
    not no_hr — so the 'wait for sync' message stays accurate."""
    # HR exists only for a narrow 20-min band == the meeting itself, so the
    # ±90-min baseline has almost no samples outside the meeting.
    m_start = DAY.replace(hour=9)
    m_end = m_start + timedelta(minutes=20)
    events = [
        {
            "start": m_start.isoformat(),
            "end": m_end.isoformat(),
            "title": "standup",
            "attendees": ["alice", "bob"],
        }
    ]
    series = [(int(m_start.timestamp()) + k * 60, 62.0) for k in range(0, 20, 2)]

    skipped: list[dict] = []
    rows = ms.score_meetings(events, series, skipped=skipped)
    assert rows == [], rows
    assert [s["reason"] for s in skipped] == ["thin_baseline"], skipped
    summary = ms.summarize_skipped(skipped)
    assert summary["no_hr"] == 0, summary  # not the sync-pending bucket
    assert summary["by_reason"]["thin_baseline"] == 1, summary


def test_score_meetings_without_skipped_is_backward_compatible():
    """Omitting the skipped arg still returns just the scored rows (no crash)."""
    events = [
        {
            "start": DAY.replace(hour=9).isoformat(),
            "end": DAY.replace(hour=9, minute=30).isoformat(),
            "title": "solo",
            "attendees": [],
        }
    ]
    series = [
        (int(DAY.replace(hour=7).timestamp()) + k * 60, 62.0) for k in range(0, 600, 2)
    ]
    assert ms.score_meetings(events, series) == []


def test_fetch_hr_refreshes_volatile_days(tmp_path, monkeypatch):
    """fetch_hr_garmin re-fetches today/yesterday (still gaining samples) but
    serves older, immutable days straight from the on-disk cache."""
    import sys
    import types

    calls: list[str] = []

    class _FakeGarmin:
        def __init__(self, *a, **k):
            pass

        def login(self, *a, **k):
            pass

        def get_heart_rates(self, date_str):
            calls.append(date_str)
            ts = int(datetime.fromisoformat(date_str + "T12:00:00+00:00").timestamp())
            return {"heartRateValues": [[ts * 1000, 70]]}

    fake = types.ModuleType("garminconnect")
    fake.Garmin = _FakeGarmin
    monkeypatch.setitem(sys.modules, "garminconnect", fake)
    monkeypatch.setenv("GARMIN_TOKEN_DIR", str(tmp_path / "tokens"))

    # Pin the clock so the module's notion of "today" can't drift from the
    # test's across a UTC-midnight boundary (which would make this flaky).
    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 7, 15, 12, 0, tzinfo=tz or timezone.utc)

    monkeypatch.setattr(ms, "datetime", _FixedDateTime)
    today = _FixedDateTime.now(timezone.utc).date()

    cache = tmp_path / "hr-cache"
    cache.mkdir()
    old_day = (today - timedelta(days=10)).strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")
    # Seed BOTH days with a stale (empty-coverage) cache file.
    for d in (old_day, today_str):
        (cache / f"hr_{d}.json").write_text("[]")

    ms.fetch_hr_garmin([old_day, today_str], str(cache))

    # Old day: served from stale cache, never re-fetched.
    assert old_day not in calls, calls
    # Today: re-fetched despite the cache existing (it may still gain samples).
    assert today_str in calls, calls
    # And its cache is refreshed with the new sample, not left empty.
    import json as _json

    assert _json.loads((cache / f"hr_{today_str}.json").read_text()), (
        "today cache refreshed"
    )




# --------------------------------------------------------------------------- #
# Exercise exclusion
# --------------------------------------------------------------------------- #
def _flat_series(day: datetime, hours: int = 12, bpm: float = 62.0, step: int = 2):
    """A quiet 2-minute HR backbone, so any bump below is unambiguous."""
    start = int(day.replace(hour=6).timestamp())
    return [(start + k * 60, bpm) for k in range(0, hours * 60, step)]


def _bump(series, start: datetime, minutes: int, delta: float):
    """Raise HR by `delta` over a window, the way a workout or a meeting does."""
    s, e = int(start.timestamp()), int((start + timedelta(minutes=minutes)).timestamp())
    return [(ts, bpm + delta if s <= ts < e else bpm) for ts, bpm in series]


def _meeting(start: datetime, minutes: int, attendees: list[str], title: str = "m"):
    return {
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=minutes)).isoformat(),
        "title": title,
        "attendees": attendees,
    }


def test_exercise_spans_pads_and_merges():
    """Cooldown is added, and a workout nested in a longer one collapses into it."""
    hike, walk = DAY.replace(hour=9), DAY.replace(hour=9, minute=20)
    spans = ms.exercise_spans([(hike, 60), (walk, 10)])
    assert len(spans) == 1, spans
    start, end = spans[0]
    assert start == int(hike.timestamp())
    # 60 minutes of hiking + the cooldown pad, with the nested walk absorbed.
    assert end == start + (60 + ms.EXERCISE_COOLDOWN_MIN) * 60, spans

    # Rows with missing fields are dropped, not guessed at.
    assert ms.exercise_spans([(None, 30), (hike, None)]) == []

    # A naive timestamp is read as UTC rather than as the machine's local time.
    # TZ is forced because CI runs in UTC, where the two are indistinguishable.
    import time

    os.environ["TZ"] = "Asia/Kolkata"
    time.tzset()
    try:
        naive = ms.exercise_spans([(hike.replace(tzinfo=None), 10)])
    finally:
        os.environ.pop("TZ", None)
        time.tzset()
    assert naive[0][0] == int(hike.timestamp()), naive


def test_drop_spans_removes_only_covered_samples():
    series = _flat_series(DAY)
    span = (
        int(DAY.replace(hour=9).timestamp()),
        int(DAY.replace(hour=10).timestamp()),
    )
    kept = ms.drop_spans(series, span and [span])
    assert kept, "samples outside the window survive"
    assert not [ts for ts, _ in kept if span[0] <= ts < span[1]], "window emptied"
    assert len(kept) == len(series) - 30, (len(kept), len(series))  # 60min / 2min
    assert ms.drop_spans(series, []) is series, "no spans is a no-op"


def test_workout_hr_is_not_scored_as_a_person():
    """A meeting overlapping a workout must not credit the attendee with the lift.

    This is the loud half of the bug: on real data it made a lunchtime walk the
    top "stressor" on the board.
    """
    workout = DAY.replace(hour=9)
    series = _bump(_flat_series(DAY), workout, 45, 40.0)  # training HR
    # A second, genuinely calm meeting so `alice` is scorable either way and the
    # comparison is about the workout window, not about having no data at all.
    events = [
        _meeting(workout.replace(minute=10), 30, ["alice"], "walk overlap"),
        _meeting(DAY.replace(hour=14), 30, ["alice"], "calm"),
    ]

    skipped: list[dict] = []
    contaminated = ms.score_meetings(events, series, skipped=skipped)
    assert max(r["dbpm"] for r in contaminated) > 20, contaminated

    spans = ms.exercise_spans([(workout, 45)])
    clean_skipped: list[dict] = []
    clean = ms.score_meetings(
        events, ms.drop_spans(series, spans), skipped=clean_skipped, exercise=spans
    )
    titles = [r["title"] for r in clean]
    assert "walk overlap" not in titles, clean
    reasons = {s["title"]: s["reason"] for s in clean_skipped}
    assert reasons.get("walk overlap") == "during_exercise", clean_skipped
    assert ms.summarize_skipped(clean_skipped)["by_reason"]["during_exercise"] == 1
    # ...and it is NOT reported as the actionable "sync your watch" bucket.
    assert ms.summarize_skipped(clean_skipped)["no_hr"] == 0


def test_workout_in_baseline_window_does_not_mask_stress():
    """The quiet half of the bug: training near a meeting inflates its baseline.

    A raised baseline makes an ordinary meeting look *calming*, which is how a
    real stressful meetup scored -0.3 instead of +10.
    """
    workout = DAY.replace(hour=9)
    meeting_at = DAY.replace(hour=10, minute=30)  # inside the +/-90min baseline
    series = _flat_series(DAY)
    series = _bump(series, workout, 45, 40.0)  # workout
    series = _bump(series, meeting_at, 30, 8.0)  # genuinely elevated meeting
    events = [_meeting(meeting_at, 30, ["alice"], "real stressor")]

    masked = ms.score_meetings(events, series)
    spans = ms.exercise_spans([(workout, 45)])
    clean = ms.score_meetings(events, ms.drop_spans(series, spans), exercise=spans)

    assert clean, "the meeting itself is still scorable"
    assert clean[0]["dbpm"] > masked[0]["dbpm"] + 1.0, (masked, clean)
    assert clean[0]["dbpm"] > 7.0, clean  # recovers close to the true +8
    people = {p["attendee"]: p for p in ms.leaderboard(clean, lam=1.0)}
    assert people["alice"]["naive"] > 7.0, people


def test_fetch_exercise_spans_degrades_when_db_is_unreachable(monkeypatch):
    """A down database must cost accuracy, not take the whole board down."""
    import builtins

    real_import = builtins.__import__

    def _no_psycopg2(name, *a, **kw):
        if name == "psycopg2":
            raise ImportError("no driver")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _no_psycopg2)
    assert ms.fetch_exercise_spans("someone") == []


def test_fetch_exercise_spans_queries_the_user(monkeypatch):
    """The rows really do come from `activity`, scoped to one user."""
    seen = {}

    class _Cur:
        def execute(self, sql, params):
            seen["sql"], seen["params"] = sql, params

        def fetchall(self):
            return [(DAY.replace(hour=9), 30)]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake = type("psycopg2", (), {"connect": staticmethod(lambda url: _Conn())})
    monkeypatch.setitem(__import__("sys").modules, "psycopg2", fake)

    spans = ms.fetch_exercise_spans("user-42")
    assert seen["params"] == ("user-42",)
    assert "FROM activity" in seen["sql"]
    assert spans == [
        (
            int(DAY.replace(hour=9).timestamp()),
            int(DAY.replace(hour=9).timestamp()) + (30 + ms.EXERCISE_COOLDOWN_MIN) * 60,
        )
    ], spans


def test_duplicate_events_do_not_vote_twice():
    """A meeting present twice in an events file must count once.

    gcal.fetch_events de-duplicates on iCalUID, but --events and the persisted
    fallback have no such key, and a repeat inflates a person's sample count
    into confidence the data does not support.
    """
    at = DAY.replace(hour=10)
    series = _bump(_flat_series(DAY), at, 30, 8.0)
    one = _meeting(at, 30, ["alice"], "standup")
    deduped = ms.dedupe_events([one, dict(one), one])
    assert len(deduped) == 1, deduped

    # Same slot, different people is a genuinely different meeting.
    other = _meeting(at, 30, ["bob"], "standup")
    assert len(ms.dedupe_events([one, other])) == 2

    # The duplicate would otherwise be scored a second time.
    assert len(ms.score_meetings([one, dict(one)], series)) == 2
    assert len(ms.score_meetings(deduped, series)) == 1


def test_main_dedupes_events_from_a_file(tmp_path, monkeypatch):
    """The wiring, not just the helper: a duplicated --events file scores once."""
    at = DAY.replace(hour=10)
    one = _meeting(at, 30, ["alice"], "standup")
    events_file = tmp_path / "events.json"
    events_file.write_text(json.dumps([one, dict(one)]))

    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "hr_2026-06-01.json").write_text(
        json.dumps([[ts, bpm] for ts, bpm in _bump(_flat_series(DAY), at, 30, 8.0)])
    )

    # No linked calendar, no interactions file, no database.
    monkeypatch.setattr(ms, "gcal_linked", lambda: False)
    monkeypatch.setattr(ms, "load_interactions", lambda: [])
    monkeypatch.setattr(ms, "fetch_exercise_spans", lambda *a, **kw: [])

    out = tmp_path / "out"
    out.mkdir()
    rc = ms.main(
        [
            "--events",
            str(events_file),
            "--hr-cache",
            str(cache),
            "--outdir",
            str(out),
            "--no-color",
        ]
    )
    assert rc == 0, rc
    report = json.loads((out / "meeting_stress.json").read_text())
    assert len(report["meetings"]) == 1, report["meetings"]
    assert report["people"][0]["n"] == 1, report["people"]


if __name__ == "__main__":
    # Tests taking a pytest fixture (monkeypatch) can only run under pytest.
    import inspect

    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and not inspect.signature(_fn).parameters:
            _fn()
    print("ok (run under pytest for the full suite)")
