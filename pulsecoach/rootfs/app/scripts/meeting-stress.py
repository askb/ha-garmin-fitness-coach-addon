#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
##############################################################################
# Meeting Stress Leaderboard — which coworker spikes my heart rate.
#
# Joins per-~2min Garmin heart rate against calendar events + attendees,
# scores each meeting vs a local 90-min baseline (dbpm / z / elev), then fits
# a ridge regression over attendee presence to de-confound who-attends-with-whom.
#
# Inputs are files only: a calendar_events.json and an HR series (cache files
# or --demo synthetic). No audio, no recording, no calendar auth.
#
# stdlib only (matches repo scripts); ridge is a hand-rolled ~kxk solve.
##############################################################################
"""Meeting stress leaderboard from calendar attendees + Garmin heart rate."""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone

BASELINE_MIN = 90          # +/- minutes of local baseline around each meeting
MIN_BASELINE_SAMPLES = 5   # need this many HR points to trust a baseline
DEFAULT_LAMBDA = 1.0       # ridge penalty
DEFAULT_MAX_ATTENDEES = 8  # bigger meetings (town-halls) are noise
MIN_RANK_MEETINGS = 3      # below this, a person's rank is "thin data"

HrSeries = list[tuple[int, float]]  # (epoch_seconds, bpm), sorted by ts


# --------------------------------------------------------------------------- #
# Parsing / HR window helpers
# --------------------------------------------------------------------------- #
def parse_ts(value: str) -> int:
    """ISO-8601 (with offset or trailing Z) -> epoch seconds (UTC)."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _bpm_between(series: HrSeries, lo: int, hi: int) -> list[float]:
    """HR values with lo <= ts < hi (series sorted by ts)."""
    keys = [ts for ts, _ in series]
    i = bisect.bisect_left(keys, lo)
    j = bisect.bisect_left(keys, hi)
    return [bpm for _, bpm in series[i:j]]


def _bpm_baseline(series: HrSeries, lo: int, hi: int, busy: list[tuple[int, int]]) -> list[float]:
    """HR in [lo, hi) excluding any time covered by a meeting interval in `busy`."""
    keys = [ts for ts, _ in series]
    i = bisect.bisect_left(keys, lo)
    j = bisect.bisect_left(keys, hi)
    out = []
    for ts, bpm in series[i:j]:
        if not any(s <= ts < e for s, e in busy):
            out.append(bpm)
    return out


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _pstdev(xs: list[float]) -> float:
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


# --------------------------------------------------------------------------- #
# Per-meeting scoring
# --------------------------------------------------------------------------- #
def score_meetings(events: list[dict], series: HrSeries,
                   max_attendees: int = DEFAULT_MAX_ATTENDEES) -> list[dict]:
    """Score each usable meeting vs its local baseline. Returns rows with dbpm/z/elev."""
    intervals = [(parse_ts(e["start"]), parse_ts(e["end"])) for e in events]
    win = BASELINE_MIN * 60
    rows: list[dict] = []

    for idx, ev in enumerate(events):
        attendees = [a for a in ev.get("attendees", []) if a]
        if not attendees or len(attendees) > max_attendees:
            continue  # solo or town-hall: skip
        s, e = intervals[idx]
        if e - s >= 6 * 3600:
            continue  # all-day / multi-hour block: skip

        meeting = _bpm_between(series, s, e)
        # baseline = surrounding window minus *every* meeting (incl. this one)
        base = _bpm_baseline(series, s - win, e + win, intervals)
        if not meeting or len(base) < MIN_BASELINE_SAMPLES:
            continue  # not enough signal

        mean_m, mean_b = _mean(meeting), _mean(base)
        std_b = max(_pstdev(base), 1.0)  # floor: avoid div-by-zero / z blow-up
        dbpm = mean_m - mean_b
        rows.append({
            "title": ev.get("title", "(untitled)"),
            "attendees": attendees,
            "dbpm": dbpm,
            "z": dbpm / std_b,
            "elev": sum(1 for b in meeting if b > mean_b) / len(meeting),
        })

    rows.sort(key=lambda r: r["dbpm"], reverse=True)
    return rows


# --------------------------------------------------------------------------- #
# Ridge regression (hand-rolled normal equations, intercept unpenalised)
# --------------------------------------------------------------------------- #
def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Solve a x = b via Gauss-Jordan with partial pivoting. n is tiny (#attendees)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            continue  # singular column; ridge penalty normally prevents this
        m[col], m[piv] = m[piv], m[col]
        pv = m[col][col]
        m[col] = [v / pv for v in m[col]]
        for r in range(n):
            if r != col and m[r][col]:
                factor = m[r][col]
                m[r] = [v - factor * m[col][k] for k, v in enumerate(m[r])]
    return [m[i][n] for i in range(n)]


def ridge_effects(rows: list[dict], lam: float = DEFAULT_LAMBDA) -> dict[str, float]:
    """Marginal bpm effect per attendee. Column 0 is an unpenalised intercept."""
    people = sorted({p for r in rows for p in r["attendees"]})
    if not people:
        return {}
    cols = ["__intercept__"] + people
    x = [[1.0] + [1.0 if p in r["attendees"] else 0.0 for p in people] for r in rows]
    y = [r["dbpm"] for r in rows]

    k = len(cols)
    xtx = [[sum(x[t][i] * x[t][j] for t in range(len(x))) for j in range(k)] for i in range(k)]
    for i in range(1, k):           # penalise attendees, not the intercept
        xtx[i][i] += lam
    xty = [sum(x[t][i] * y[t] for t in range(len(x))) for i in range(k)]
    w = _solve(xtx, xty)
    return dict(zip(people, w[1:]))


def naive_effects(rows: list[dict]) -> dict[str, list[float]]:
    """Per attendee: list of meeting dbpm values where they were present."""
    out: dict[str, list[float]] = {}
    for r in rows:
        for p in r["attendees"]:
            out.setdefault(p, []).append(r["dbpm"])
    return out


def _label(ridge: float, n: int) -> str:
    if n < MIN_RANK_MEETINGS:
        return "thin data"
    if ridge >= 5.0:
        return "prime suspect"
    if ridge >= 2.0:
        return "mild stressor"
    if ridge >= 0.5:
        return "slightly raises HR"
    if ridge > -0.5:
        return "neutral"
    return "calming"


def _reliability(n: int) -> str:
    return "high" if n >= 5 else "med" if n >= MIN_RANK_MEETINGS else "low"


def leaderboard(rows: list[dict], lam: float = DEFAULT_LAMBDA) -> list[dict]:
    """Combine naive + ridge into a ranked per-person table."""
    naive = naive_effects(rows)
    ridge = ridge_effects(rows, lam)
    people = []
    for p, deltas in naive.items():
        n = len(deltas)
        r = ridge.get(p, 0.0)
        people.append({
            "attendee": p,
            "n": n,
            "naive": _mean(deltas),
            "ridge": r,
            "reliability": _reliability(n),
            "label": _label(r, n),
        })
    people.sort(key=lambda d: d["ridge"], reverse=True)
    return people


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def _c(text: str, value: float, enable: bool) -> str:
    if not enable:
        return text
    code = "31" if value > 0.5 else "32" if value < -0.5 else "90"
    return f"\033[{code}m{text}\033[0m"


def print_report(meetings: list[dict], people: list[dict], color: bool) -> None:
    print("\nMEETING STRESS   mean HR over surrounding baseline")
    print(f"  {'dbpm':>6} {'z':>6} {'elev':>5}  {'meeting':<22} attendees")
    for r in meetings:
        line = f"  {r['dbpm']:+6.1f} {r['z']:6.2f} {r['elev']*100:4.0f}%  {r['title'][:22]:<22} {', '.join(r['attendees'])}"
        print(_c(line, r["dbpm"], color))

    print("\nPER-PERSON   ranked by ridge marginal effect (bpm)")
    print(f"  {'attendee':<16} {'n':>3} {'naive':>7} {'ridge':>7} {'rel':>5}  label")
    for p in people:
        line = (f"  {p['attendee']:<16} {p['n']:>3} {p['naive']:>7.2f} "
                f"{p['ridge']:>7.2f} {p['reliability']:>5}  {p['label']}")
        print(_c(line, p["ridge"], color))
    print()


def write_csvs(meetings: list[dict], people: list[dict], outdir: str) -> None:
    with open(os.path.join(outdir, "meeting_stress.json"), "w") as f:
        json.dump({"generated": datetime.now(timezone.utc).isoformat(),
                   "meetings": meetings, "people": people}, f, indent=1)
    with open(os.path.join(outdir, "meeting_scores.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dbpm", "z", "elev", "title", "attendees"])
        for r in meetings:
            w.writerow([f"{r['dbpm']:.2f}", f"{r['z']:.3f}", f"{r['elev']:.3f}",
                        r["title"], "|".join(r["attendees"])])
    with open(os.path.join(outdir, "person_scores.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["attendee", "n", "naive", "ridge", "reliability", "label"])
        for p in people:
            w.writerow([p["attendee"], p["n"], f"{p['naive']:.3f}",
                        f"{p['ridge']:.3f}", p["reliability"], p["label"]])
    print(f"wrote meeting_scores.csv, person_scores.csv -> {outdir}")


# --------------------------------------------------------------------------- #
# HR sources
# --------------------------------------------------------------------------- #
def load_hr_cache(cache_dir: str) -> HrSeries:
    """Load every cache/hr_*.json ([[epoch_s, bpm], ...]) into one sorted series."""
    series: HrSeries = []
    if not os.path.isdir(cache_dir):
        return series  # first run without --fetch: fall through to friendly error
    for name in sorted(os.listdir(cache_dir)):
        if name.startswith("hr_") and name.endswith(".json"):
            with open(os.path.join(cache_dir, name)) as f:
                series.extend((int(ts), float(bpm)) for ts, bpm in json.load(f) if bpm is not None)
    series.sort()
    return series


def _migrate_garth_tokens(token_dir: str) -> None:
    """Convert legacy garth oauth2_token.json to garminconnect 0.3.x native format.

    Same migration as pulsecoach garmin-sync.py — generate-garmin-tokens.py emits
    garth-format files, which newer garminconnect can't load directly.
    """
    import base64

    native = os.path.join(token_dir, "garmin_tokens.json")
    legacy = os.path.join(token_dir, "oauth2_token.json")
    if os.path.exists(native) or not os.path.exists(legacy):
        return
    with open(legacy) as f:
        oauth2 = json.load(f)
    access_token = oauth2.get("access_token", "")
    if not access_token:
        return
    client_id = ""
    try:
        part = access_token.split(".")[1]
        pad = -len(part) % 4
        jwt = json.loads(base64.urlsafe_b64decode(part + "=" * pad))
        client_id = jwt.get("client_id", "")
    except Exception:
        pass
    fd = os.open(native, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"di_token": access_token,
                   "di_refresh_token": oauth2.get("refresh_token", ""),
                   "di_client_id": client_id}, f, indent=2)


def fetch_hr_garmin(dates: list[str], cache_dir: str) -> HrSeries:
    """Real path: pull ~2-min HR per date via garminconnect, cache, return series."""
    from garminconnect import Garmin  # type: ignore

    token_dir = os.environ.get("GARMIN_TOKEN_DIR", "/data/garmin-tokens")
    _migrate_garth_tokens(token_dir)
    client = Garmin(os.environ.get("GARMIN_EMAIL", "token-user"),
                    os.environ.get("GARMIN_PASSWORD", ""))
    client.login(tokenstore=token_dir)

    os.makedirs(cache_dir, exist_ok=True)
    series: HrSeries = []
    for date_str in dates:
        path = os.path.join(cache_dir, f"hr_{date_str}.json")
        if os.path.exists(path):
            with open(path) as f:
                pairs = json.load(f)
        else:
            data = client.get_heart_rates(date_str) or {}
            pairs = [[int(ms // 1000), bpm] for ms, bpm in data.get("heartRateValues") or []
                     if bpm is not None]
            with open(path, "w") as f:
                json.dump(pairs, f)
        series.extend((int(ts), float(bpm)) for ts, bpm in pairs)
    series.sort()
    return series


# --------------------------------------------------------------------------- #
# Synthetic demo data
# --------------------------------------------------------------------------- #
def make_demo(seed: int = 7) -> tuple[list[dict], HrSeries]:
    """Post-like dataset: 8 attendees, ~18 meetings, synthetic 2-min HR.

    `manager` attends almost everything (the confounder); the leaderboard should
    still clear them via ridge while flagging the real stressor `pm_growth`.
    """
    rng = random.Random(seed)
    effects = {  # true marginal bpm each attendee adds to a meeting
        "pm_growth": 8.0, "team_1_person": 4.0, "engg_1": 1.3, "ios_engg": 1.0,
        "team_2_person": 0.8, "manager": 0.2, "engg_2": -1.0, "senior_dev": -3.5,
    }
    people = list(effects)

    # Build meetings on weekdays, business hours, 2026-06-01 (Mon) onward.
    base_day = datetime(2026, 6, 1, tzinfo=timezone.utc)
    events: list[dict] = []
    workdays = [base_day + timedelta(days=d) for d in range(14) if (base_day + timedelta(days=d)).weekday() < 5]
    titles = ["standup", "1:1", "planning", "review", "sync", "all-hands prep",
              "retro", "design", "roadmap", "incident review"]
    for day in workdays:
        for _ in range(rng.randint(1, 3)):
            hour = rng.choice([9, 10, 11, 13, 14, 15, 16])
            start = day.replace(hour=hour, minute=0)
            dur = rng.choice([30, 45, 60])
            others = rng.sample([p for p in people if p != "manager"], rng.randint(1, 4))
            attendees = (["manager"] + others) if rng.random() < 0.75 else others
            events.append({
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=dur)).isoformat(),
                "title": rng.choice(titles),
                "attendees": attendees,
            })
    events = events[:18]

    # Mark each meeting's true elevation = sum of attendee effects.
    meeting_lift: list[tuple[int, int, float]] = []
    for ev in events:
        s, e = parse_ts(ev["start"]), parse_ts(ev["end"])
        meeting_lift.append((s, e, sum(effects[a] for a in ev["attendees"])))

    # Generate 2-min HR across each workday: circadian-ish drift + noise + meeting lift.
    series: HrSeries = []
    for day in workdays:
        day_start = int(day.replace(hour=7).timestamp())
        for k in range(0, 11 * 60, 2):  # 07:00..18:00, every 2 min
            ts = day_start + k * 60
            circadian = 6.0 * math.sin(k / (11 * 60) * math.pi)  # gentle daytime hump
            lift = sum(l for s, e, l in meeting_lift if s <= ts < e)
            bpm = 62 + circadian + lift + rng.gauss(0, 2.0)
            series.append((ts, round(bpm, 1)))
    series.sort()
    return events, series


# --------------------------------------------------------------------------- #
# Google Calendar (linked-calendar mode)
# --------------------------------------------------------------------------- #
GCAL_TOKEN_PATH = "/data/gcal-token.json"
GCAL_DROP_PATH = "/share/pulsecoach/gcal-token.json"


def _adopt_gcal_token() -> None:
    """Move a user-dropped token from /share (world-readable) into /data."""
    if os.path.exists(GCAL_DROP_PATH) and os.path.isdir("/data"):
        import shutil

        shutil.move(GCAL_DROP_PATH, GCAL_TOKEN_PATH)
        os.chmod(GCAL_TOKEN_PATH, 0o600)
        print("Adopted gcal-token.json from /share into /data")


def gcal_linked() -> bool:
    """True when a Google Calendar refresh token is available."""
    _adopt_gcal_token()
    return os.path.exists(GCAL_TOKEN_PATH)


def _gcal_item_to_event(item: dict) -> dict | None:
    """Map one Calendar API item to our event schema; None if unusable."""
    start = item.get("start", {}).get("dateTime")
    end = item.get("end", {}).get("dateTime")
    if not start or not end:
        return None  # all-day event
    attendees = []
    for att in item.get("attendees", []):
        if (att.get("responseStatus") == "declined"
                or att.get("resource") or att.get("self")):
            continue
        name = att.get("displayName") or att.get("email", "").split("@")[0]
        if name:
            attendees.append(name)
    if not attendees:
        return None
    return {
        "start": start,
        "end": end,
        "title": item.get("summary", "(untitled)"),
        "attendees": sorted(set(attendees)),
    }


def fetch_events_gcal(days: int) -> list[dict]:
    """Pull the last `days` of primary-calendar events via the Calendar API.

    Uses the refresh token from generate-gcal-token.py; recurrences arrive
    pre-expanded (singleEvents). Declined attendees, rooms, and self are
    dropped — same policy as ics_to_events.py.
    """
    import urllib.parse
    import urllib.request

    with open(GCAL_TOKEN_PATH) as f:
        tok = json.load(f)

    body = urllib.parse.urlencode({
        "client_id": tok["client_id"],
        "client_secret": tok["client_secret"],
        "refresh_token": tok["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body)
    with urllib.request.urlopen(req, timeout=30) as resp:
        access = json.load(resp)["access_token"]

    now = datetime.now(timezone.utc)
    base_params = {
        "timeMin": (now - timedelta(days=days)).isoformat(),
        "timeMax": now.isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "250",
    }
    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    events: list[dict] = []
    page_token = ""
    while True:
        params = dict(base_params)
        if page_token:
            params["pageToken"] = page_token
        req = urllib.request.Request(
            f"{url}?{urllib.parse.urlencode(params)}",
            headers={"Authorization": f"Bearer {access}"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)

        for item in data.get("items", []):
            ev = _gcal_item_to_event(item)
            if ev:
                events.append(ev)

        page_token = data.get("nextPageToken", "")
        if not page_token:
            break

    print(f"Fetched {len(events)} meetings from Google Calendar (last {days}d)")
    return events


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    share = "/share/pulsecoach"
    default_events = os.path.join(share, "calendar_events.json")

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events",
                    default=default_events if os.path.exists(default_events) else None,
                    help="calendar_events.json (default: /share/pulsecoach/ if present)")
    ap.add_argument("--hr-cache", default="/data/hr-cache" if os.path.isdir("/data") else "cache",
                    help="dir of hr_YYYY-MM-DD.json files")
    ap.add_argument("--fetch", action="store_true", help="pull HR live from Garmin (needs tokens)")
    ap.add_argument("--demo", action="store_true", help="run on synthetic post-like data")
    ap.add_argument("--lambda", dest="lam", type=float, default=DEFAULT_LAMBDA)
    ap.add_argument("--max-attendees", type=int, default=DEFAULT_MAX_ATTENDEES)
    ap.add_argument("--outdir", default=share if os.path.isdir(share) else ".")
    ap.add_argument("--days", type=int, default=30,
                    help="linked-calendar lookback window (days)")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args(argv)

    if args.demo:
        events, series = make_demo()
    else:
        if args.events:
            with open(args.events) as f:
                events = json.load(f)
        elif gcal_linked():
            events = fetch_events_gcal(args.days)
        else:
            ap.error("--events is required (or link Google Calendar / use --demo)")
        if args.fetch:
            dates = sorted({parse_ts(e["start"]) for e in events})
            dates = sorted({datetime.fromtimestamp(d, timezone.utc).strftime("%Y-%m-%d") for d in dates})
            series = fetch_hr_garmin(dates, args.hr_cache)
        else:
            series = load_hr_cache(args.hr_cache)

    if not series:
        print("No heart-rate samples found. Use --demo, --fetch, or populate --hr-cache.",
              file=sys.stderr)
        return 1

    meetings = score_meetings(events, series, args.max_attendees)
    if not meetings:
        print("No scorable meetings (all solo / too big / outside HR coverage).", file=sys.stderr)
        return 1
    people = leaderboard(meetings, args.lam)

    color = sys.stdout.isatty() and not args.no_color
    print_report(meetings, people, color)
    write_csvs(meetings, people, args.outdir)
    return 0


def _clear_status() -> None:
    """Clear the auth-server's run lock (same convention as metrics-compute)."""
    path = os.path.join(os.environ.get("GARMIN_TOKEN_DIR", "/data/garmin-tokens"),
                        ".meeting_stress_status")
    try:
        if os.path.exists(path):
            with open(path, "w") as f:
                json.dump({"running": False, "finished": datetime.now(timezone.utc).isoformat()}, f)
    except OSError:
        pass


if __name__ == "__main__":
    try:
        code = main()
    finally:
        _clear_status()
    raise SystemExit(code)
