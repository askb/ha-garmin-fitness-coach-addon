#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
##############################################################################
# Convert a Google Calendar .ics export into calendar_events.json for
# meeting_stress.py. Expands recurring events (RRULE/EXDATE), keeps only
# attendees who did not decline, and drops yourself + room resources.
#
# One-off preprocessing tool; needs: pip install icalendar recurring-ical-events
##############################################################################
"""ICS export -> calendar_events.json (attendee display names, recurrences expanded)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta, timezone

try:
    import icalendar
    import recurring_ical_events
except ImportError:
    print("pip install icalendar recurring-ical-events", file=sys.stderr)
    raise SystemExit(1)


def _strip_mailto(value: str) -> str:
    """Remove mailto: prefix case-insensitively (Google exports use MAILTO: too)."""
    return value[7:] if value[:7].lower() == "mailto:" else value


def _name(att) -> str:
    """Prefer CN display name, fall back to the email local part."""
    cn = att.params.get("CN", "")
    email = _strip_mailto(str(att))
    if cn and "@" not in cn:
        return cn
    return email.split("@")[0]


def convert(ics_path: str, self_email: str, start: date, end: date) -> list[dict]:
    with open(ics_path, "rb") as f:
        cal = icalendar.Calendar.from_ical(f.read())

    events = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        dtstart, dtend = ev.get("DTSTART"), ev.get("DTEND")
        if not dtstart or not dtend:
            continue
        s, e = dtstart.dt, dtend.dt
        if not isinstance(s, datetime):  # all-day event -> skip (no HR window)
            continue
        if s.tzinfo is None:
            s, e = s.replace(tzinfo=timezone.utc), e.replace(tzinfo=timezone.utc)

        raw = ev.get("ATTENDEE", [])
        if not isinstance(raw, list):
            raw = [raw]
        attendees = []
        for att in raw:
            email = _strip_mailto(str(att)).lower()
            if att.params.get("PARTSTAT", "").upper() == "DECLINED":
                continue  # they weren't there
            if att.params.get("CUTYPE", "").upper() in ("RESOURCE", "ROOM"):
                continue  # meeting rooms aren't coworkers
            if email == self_email.lower():
                continue  # you attend everything; collinear with intercept
            attendees.append(_name(att))
        if not attendees:
            continue

        events.append({
            "start": s.isoformat(),
            "end": e.isoformat(),
            "title": str(ev.get("SUMMARY", "(untitled)")),
            "attendees": sorted(set(attendees)),
        })

    events.sort(key=lambda ev: ev["start"])
    return events


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ics", help="path to exported .ics file")
    ap.add_argument("--self", required=True, dest="self_email",
                    help="your email (excluded from attendee lists)")
    ap.add_argument("--days", type=int, default=30, help="how far back from today")
    ap.add_argument("--out", default="calendar_events.json")
    args = ap.parse_args()

    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=args.days + 1)
    events = convert(args.ics, args.self_email, start, end)

    with open(args.out, "w") as f:
        json.dump(events, f, indent=1)
    people = sorted({p for ev in events for p in ev["attendees"]})
    print(f"{len(events)} meetings ({start}..{end}), {len(people)} distinct attendees -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
