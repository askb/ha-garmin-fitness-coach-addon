# SPDX-FileCopyrightText: 2026 Anil Belur
# SPDX-License-Identifier: Apache-2.0
"""Generate synthetic 90-day training fixture data for deterministic tests.

Creates daily TRIMP loads, HR metrics, sleep, stress, and expected
EWMA CTL/ATL/TSB/ACWR outputs for verifying metrics-compute.py accuracy.
"""

import json
import random
from datetime import date, timedelta

random.seed(42)  # deterministic

DAYS = 90
START_DATE = date(2025, 1, 1)

# Engine-conformant constants (mirror metrics-compute.py / the app engine in
# packages/engine/src/strain). Span EWMA alpha = 2/(N+1); ACWR is the ratio of
# the 7-day to 28-day rolling means; ramp is the absolute CTL change vs 7 days
# ago. These intentionally replace the old time-constant EWMA + ATL/CTL ACWR.
ALPHA_CTL = 2 / (42 + 1)
ALPHA_ATL = 2 / (7 + 1)
ACWR_ACUTE_DAYS = 7
ACWR_CHRONIC_DAYS = 28


def generate_daily_loads() -> list[dict]:
    """Generate 90 days of synthetic daily training data."""
    records = []

    for i in range(DAYS):
        d = START_DATE + timedelta(days=i)
        day_of_week = d.weekday()

        # Simulate realistic training pattern:
        # Mon/Wed/Fri: moderate runs, Tue/Thu: easy, Sat: long run, Sun: rest
        if day_of_week == 6:  # Sunday rest
            trimp = random.uniform(0, 15)
        elif day_of_week == 5:  # Saturday long run
            trimp = random.uniform(120, 200)
        elif day_of_week in (1, 3):  # Tue/Thu easy
            trimp = random.uniform(30, 60)
        else:  # Mon/Wed/Fri moderate
            trimp = random.uniform(60, 120)

        trimp = round(trimp, 1)

        records.append({
            "date": d.isoformat(),
            "trimp": trimp,
            "garmin_training_load": round(trimp * 0.8, 1),  # approximate conversion
            "resting_hr": random.randint(48, 58),
            "max_hr": random.randint(155, 185),
            "hrv": random.randint(35, 85),
            "stress_score": random.randint(20, 60),
            "sleep_score": random.randint(60, 95),
            "total_sleep_minutes": random.randint(350, 520),
            "deep_sleep_minutes": random.randint(40, 120),
            "rem_sleep_minutes": random.randint(60, 140),
            "body_battery_start": random.randint(30, 80),
            "body_battery_end": random.randint(5, 50),
            "spo2": random.randint(94, 99),
        })

    # Compute expected EWMA outputs over the full series, mirroring
    # metrics-compute.py compute_ewma_loads exactly (CTL/ATL seeded with the
    # first day's load; no update applied on day 0; ACWR from rolling means).
    loads = [r["trimp"] for r in records]
    ctl = loads[0]
    atl = loads[0]

    for i, record in enumerate(records):
        load = loads[i]
        if i > 0:
            ctl = ALPHA_CTL * load + (1 - ALPHA_CTL) * ctl
            atl = ALPHA_ATL * load + (1 - ALPHA_ATL) * atl
        tsb = ctl - atl

        acute_window = loads[max(0, i - (ACWR_ACUTE_DAYS - 1)):i + 1]
        chronic_window = loads[max(0, i - (ACWR_CHRONIC_DAYS - 1)):i + 1]
        acute = sum(acute_window) / max(1, len(acute_window))
        chronic = sum(chronic_window) / max(1, len(chronic_window))
        if chronic == 0:
            acwr = 2.0 if acute > 0 else 1.0
        else:
            acwr = acute / chronic

        record["expected_ctl"] = round(ctl, 2)
        record["expected_atl"] = round(atl, 2)
        record["expected_tsb"] = round(tsb, 2)
        record["expected_acwr"] = round(acwr, 3)

    return records


if __name__ == "__main__":
    data = generate_daily_loads()
    with open("tests/fixtures/synthetic_90day.json", "w") as f:
        json.dump(data, f, indent=2)
    print(f"Generated {len(data)} days of synthetic data")
    print(f"  Date range: {data[0]['date']} to {data[-1]['date']}")
    print(f"  Final CTL: {data[-1]['expected_ctl']}")
    print(f"  Final ATL: {data[-1]['expected_atl']}")
    print(f"  Final TSB: {data[-1]['expected_tsb']}")
