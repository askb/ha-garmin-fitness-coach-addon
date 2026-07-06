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
    ev = ms._gcal_item_to_event(item)
    assert ev["attendees"] == ["Alice", "carol"], ev
    # all-day events (date, no dateTime) are dropped
    assert ms._gcal_item_to_event({"start": {"date": "2026-07-01"},
                                   "end": {"date": "2026-07-02"}}) is None


if __name__ == "__main__":
    test_ridge_deconfounds_bystander()
    test_solo_and_oversize_meetings_skipped()
    test_gcal_item_mapping()
    print("ok")
