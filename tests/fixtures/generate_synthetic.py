# SPDX-FileCopyrightText: 2026 Anil Belur
# SPDX-License-Identifier: Apache-2.0
"""Generate synthetic 90-day training fixture data for deterministic tests.

Creates daily TRIMP loads, HR metrics, sleep, stress, and expected
EWMA CTL/ATL/TSB/ACWR outputs for verifying metrics-compute.py accuracy.
"""

import json
import math
import random
from datetime import date, timedelta

random.seed(42)  # deterministic

DAYS = 90
START_DATE = date(2025, 1, 1)

CTL_DECAY = 1 - math.exp(-1 / 42)
ATL_DECAY = 1 - math.exp(-1 / 7)


def generate_daily_loads() -> list[dict]:
    """Generate 90 days of synthetic daily training data."""
    records = []
    ctl = 0.0
    atl = 0.0

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

        # EWMA computation (must match metrics-compute.py exactly)
        ctl = ctl + CTL_DECAY * (trimp - ctl)
        atl = atl + ATL_DECAY * (trimp - atl)
        tsb = ctl - atl
        acwr = round(atl / ctl, 3) if ctl > 0.5 else None
        ramp_rate = round(ctl - (ctl - CTL_DECAY * (trimp - ctl)), 2) if i > 0 else 0

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
            # Expected EWMA outputs
            "expected_ctl": round(ctl, 2),
            "expected_atl": round(atl, 2),
            "expected_tsb": round(tsb, 2),
            "expected_acwr": acwr,
        })

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
