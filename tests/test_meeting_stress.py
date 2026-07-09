#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
"""Self-check for meeting_stress: baseline math + ridge de-confounding.

Run: python -m pytest tests/test_meeting_stress.py   (or: python tests/test_meeting_stress.py)
"""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPT = (Path(__file__).resolve().parents[1] / "pulsecoach" / "rootfs"
           / "app" / "scripts" / "meeting-stress.py")
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
        (1, 14, ["bob", "dave"]),       # bob without alice -> neutral
        (2, 9, ["alice", "bob", "carol"]),
        (2, 14, ["bob", "dave"]),       # bob without alice -> neutral
        (3, 9, ["alice", "carol"]),
        (3, 14, ["carol", "dave"]),     # carol calming, no alice
        (4, 9, ["alice", "bob", "dave"]),
        (4, 14, ["carol", "bob"]),
    ]
    events, windows = [], []
    for d, h, att in specs:
        start = DAY.replace(hour=h) + timedelta(days=d)
        end = start + timedelta(minutes=40)
        events.append({"start": start.isoformat(), "end": end.isoformat(),
                       "title": "m", "attendees": att})
        windows.append((int(start.timestamp()), int(end.timestamp()),
                        sum(lift[a] for a in att)))

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
    assert people["bob"]["naive"] > 2.0, people["bob"]      # confounded
    assert abs(people["bob"]["ridge"]) < 2.5, people["bob"]  # de-confounded ~0
    assert people["bob"]["naive"] - people["bob"]["ridge"] > 1.5, people["bob"]

    # 3. carol reads as calming (negative effect).
    assert people["carol"]["ridge"] < -1.0, people["carol"]


def test_solo_and_oversize_meetings_skipped():
    events = [
        {"start": DAY.replace(hour=9).isoformat(),
         "end": DAY.replace(hour=9, minute=30).isoformat(), "title": "solo", "attendees": []},
        {"start": DAY.replace(hour=10).isoformat(),
         "end": DAY.replace(hour=10, minute=30).isoformat(), "title": "townhall",
         "attendees": [f"p{i}" for i in range(20)]},
    ]
    series = [(int(DAY.replace(hour=7).timestamp()) + k * 60, 62.0) for k in range(0, 600, 2)]
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
    assert gcal._item_to_event({"start": {"date": "2026-07-01"},
                                "end": {"date": "2026-07-02"}}) is None


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
        "primary": [_item("uid-shared", 9, "standup", "alice"),
                    _item("uid-a", 10, "1:1", "bob")],
        "team@x.org": [_item("uid-shared", 9, "standup", "alice"),
                       _item("uid-b", 11, "review", "carol")],
    }
    monkeypatch.setattr(gcal, "load_token", lambda: {"ok": True})
    monkeypatch.setattr(gcal, "_refresh_access_token", lambda tok: "access")
    monkeypatch.setattr(gcal, "selected_calendar_ids",
                        lambda: ["primary", "team@x.org"])
    monkeypatch.setattr(gcal, "_list_events_for_calendar",
                        lambda access, cid, days: per_cal[cid])

    events = gcal.fetch_events(14)
    titles = sorted(e["title"] for e in events)
    assert titles == ["1:1", "review", "standup"], titles

    # Recurring series: two occurrences share one iCalUID (singleEvents=true)
    # but differ by start — they must NOT be de-duplicated into one.
    rec = [
        _item("uid-rec", 9, "weekly", "alice"),
        {**_item("uid-rec", 9, "weekly", "alice"),
         "start": {"dateTime": "2026-07-08T09:00:00+10:00"},
         "end": {"dateTime": "2026-07-08T09:30:00+10:00"}},
    ]
    monkeypatch.setattr(gcal, "selected_calendar_ids", lambda: ["primary"])
    monkeypatch.setattr(gcal, "_list_events_for_calendar",
                        lambda access, cid, days: rec)
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
        {"start": meet_start.isoformat(), "end": meet_end.isoformat(),
         "title": "standup", "attendees": ["alice", "bob"]},
        {"start": inter_start.isoformat(), "end": inter_end.isoformat(),
         "title": "interaction: Mum", "attendees": ["Mum"]},
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
    events = [{"start": m_start.isoformat(), "end": m_end.isoformat(),
               "title": "standup", "attendees": ["alice", "bob"]}]
    series = [(int(m_start.timestamp()) + k * 60, 62.0) for k in range(0, 20, 2)]

    skipped: list[dict] = []
    rows = ms.score_meetings(events, series, skipped=skipped)
    assert rows == [], rows
    assert [s["reason"] for s in skipped] == ["thin_baseline"], skipped
    summary = ms.summarize_skipped(skipped)
    assert summary["no_hr"] == 0, summary            # not the sync-pending bucket
    assert summary["by_reason"]["thin_baseline"] == 1, summary


def test_score_meetings_without_skipped_is_backward_compatible():
    """Omitting the skipped arg still returns just the scored rows (no crash)."""
    events = [{"start": DAY.replace(hour=9).isoformat(),
               "end": DAY.replace(hour=9, minute=30).isoformat(),
               "title": "solo", "attendees": []}]
    series = [(int(DAY.replace(hour=7).timestamp()) + k * 60, 62.0)
              for k in range(0, 600, 2)]
    assert ms.score_meetings(events, series) == []


if __name__ == "__main__":
    test_ridge_deconfounds_bystander()
    test_solo_and_oversize_meetings_skipped()
    test_gcal_item_mapping()
    test_interactions_jsonl()
    test_skipped_reports_no_hr_interactions()
    test_thin_baseline_is_distinct_from_no_hr()
    test_score_meetings_without_skipped_is_backward_compatible()
    print("ok")
