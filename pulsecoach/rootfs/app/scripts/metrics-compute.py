#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""PulseCoach Advanced Metrics Computation Service.

Computes ACWR, CTL, ATL, TSB, ramp rate, and effective VO2max from
existing daily_metric and activity data. Upserts into advanced_metric table.
Runs on startup for full backfill, then loops every COMPUTE_INTERVAL_MINUTES.
"""

import math
import os
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from zoneinfo import ZoneInfo

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 not installed", file=sys.stderr)
    sys.exit(1)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres@127.0.0.1:5432/pulsecoach"
)
USER_ID = os.environ.get("GARMIN_USER_ID", "seed-user-001")
COMPUTE_INTERVAL_MINUTES = int(os.environ.get("COMPUTE_INTERVAL_MINUTES", "60"))

# Timezone for date boundary calculations
_tz_name = os.environ.get("USER_TIMEZONE", "UTC")
try:
    USER_TZ = ZoneInfo(_tz_name)
except (KeyError, ValueError):
    print(f"[metrics-compute] WARNING: Invalid timezone '{_tz_name}', using UTC", file=sys.stderr)
    USER_TZ = ZoneInfo("UTC")

# EWMA decay constants
ATL_DECAY = 1 - math.exp(-1 / 7)   # 7-day time constant
CTL_DECAY = 1 - math.exp(-1 / 42)  # 42-day time constant


def get_db():
    return psycopg2.connect(DATABASE_URL)


def ensure_advanced_metric_table(cur):
    """Create advanced_metric table and ensure unique constraint exists."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS advanced_metric (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id TEXT NOT NULL,
            date DATE NOT NULL,
            ctl DOUBLE PRECISION,
            atl DOUBLE PRECISION,
            tsb DOUBLE PRECISION,
            acwr DOUBLE PRECISION,
            ramp_rate DOUBLE PRECISION,
            cp DOUBLE PRECISION,
            w_prime DOUBLE PRECISION,
            frc DOUBLE PRECISION,
            mftp DOUBLE PRECISION,
            tte DOUBLE PRECISION,
            effective_vo2max DOUBLE PRECISION,
            computed_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, date)
        );
    """)
    # If the table was created by Drizzle push (without the constraint),
    # CREATE TABLE IF NOT EXISTS won't add it. Ensure it exists separately.
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'advanced_metric_user_date_unique'
                  AND conrelid = 'advanced_metric'::regclass
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'advanced_metric_user_id_date_key'
                  AND conrelid = 'advanced_metric'::regclass
            ) THEN
                ALTER TABLE advanced_metric
                    ADD CONSTRAINT advanced_metric_user_date_unique
                    UNIQUE (user_id, date);
            END IF;
        END $$;
    """)


def fetch_daily_loads(cur, user_id):
    """Fetch training load scores per date.

    Uses garmin_training_load from daily_metric if available, else
    sum of TRIMP from activities.
    Returns dict: {date_str: load_value}
    """
    cur.execute("""
        SELECT date::text, COALESCE(garmin_training_load, 0) as load
        FROM daily_metric
        WHERE user_id = %s AND date IS NOT NULL
        ORDER BY date ASC
    """, (user_id,))
    daily_rows = {row['date']: float(row['load']) for row in cur.fetchall()}

    # Fill in from activity TRIMP where daily_metric has no garmin_training_load
    cur.execute("""
        SELECT DATE(started_at)::text as activity_date,
               SUM(COALESCE(trimp_score, 0)) as total_trimp
        FROM activity
        WHERE user_id = %s
        GROUP BY activity_date
        ORDER BY activity_date ASC
    """, (user_id,))
    for row in cur.fetchall():
        d, trimp = row['activity_date'], float(row['total_trimp'])
        if d in daily_rows and daily_rows[d] == 0 and trimp > 0:
            daily_rows[d] = trimp

    return daily_rows


def compute_ewma_loads(daily_loads: dict) -> dict:
    """Compute CTL (42-day EWMA) and ATL (7-day EWMA) for each date.

    Returns dict: {date_str: {ctl, atl, tsb, acwr, ramp_rate}}
    """
    if not daily_loads:
        return {}

    dates = sorted(daily_loads.keys())
    start = date.fromisoformat(dates[0])
    end = date.fromisoformat(dates[-1])

    ctl = 0.0
    atl = 0.0
    results = {}
    current = start

    while current <= end:
        d_str = current.isoformat()
        load = daily_loads.get(d_str, 0.0)

        ctl = ctl + CTL_DECAY * (load - ctl)
        atl = atl + ATL_DECAY * (load - atl)
        tsb = ctl - atl
        acwr = (atl / ctl) if ctl > 0.5 else None

        # Ramp rate: % change in CTL vs 7 days ago
        prev_key = (current - timedelta(days=7)).isoformat()
        if prev_key in results:
            prev_ctl = results[prev_key]["ctl"]
            ramp_rate = ((ctl - prev_ctl) / prev_ctl * 100) if prev_ctl > 0.5 else None
        else:
            ramp_rate = None

        results[d_str] = {
            "ctl": round(ctl, 2),
            "atl": round(atl, 2),
            "tsb": round(tsb, 2),
            "acwr": round(acwr, 3) if acwr is not None else None,
            "ramp_rate": round(ramp_rate, 2) if ramp_rate is not None else None,
        }

        current += timedelta(days=1)

    return results


def compute_effective_vo2max(cur, user_id) -> dict:
    """Compute effective VO2max per date from activity vo2max_estimate column.

    Returns dict: {date_str: effective_vo2max}
    """
    cur.execute("""
        SELECT DATE(started_at)::text as d, MAX(vo2max_estimate) as vo2max
        FROM activity
        WHERE user_id = %s AND vo2max_estimate IS NOT NULL
        GROUP BY d
        ORDER BY d ASC
    """, (user_id,))
    return {row['d']: float(row['vo2max']) for row in cur.fetchall()}


def compute_critical_power(cur, user_id) -> dict:
    """Rough CP estimation from activity data using 2-parameter model.

    Uses avg_power/normalized_power from activities. Computes CP for each
    date that has at least 3 different duration buckets in a 90-day rolling
    window. Returns empty dict if insufficient power data exists.
    Returns dict: {date_str: {cp, w_prime, frc, mftp, tte}}
    """
    cur.execute("""
        SELECT
            DATE(started_at)::text as d,
            duration_minutes,
            avg_power,
            normalized_power
        FROM activity
        WHERE user_id = %s
          AND avg_power IS NOT NULL
          AND avg_power > 50
          AND duration_minutes >= 10
        ORDER BY started_at ASC
    """, (user_id,))
    rows = cur.fetchall()
    if len(rows) < 5:
        return {}

    observations = []
    for row in rows:
        d_str, dur_min, avg_pwr, norm_pwr = (
            row['d'], row['duration_minutes'], row['avg_power'], row['normalized_power']
        )
        pwr = norm_pwr if norm_pwr else avg_pwr
        bucket = min(int(dur_min / 10) * 10, 120)
        observations.append((date.fromisoformat(d_str), bucket, float(pwr)))

    unique_dates = sorted(set(d for d, _, _ in observations))

    result = {}
    for target_date in unique_dates:
        window_start = target_date - timedelta(days=90)
        window_obs = [(b, p) for d, b, p in observations
                      if window_start <= d <= target_date]

        # Best power per duration bucket within the window
        buckets: dict = defaultdict(float)
        for bucket, power in window_obs:
            buckets[bucket] = max(buckets[bucket], power)

        if len(buckets) < 3:
            continue

        best_20 = max(buckets.get(20, 0), buckets.get(30, 0))
        best_60 = buckets.get(60, 0)

        if not best_20 or not best_60 or best_20 <= best_60:
            continue

        # 2-parameter CP model
        t_short, t_long = 1200, 3600  # 20 min, 60 min in seconds
        cp = (best_20 * t_short - best_60 * t_long) / (t_short - t_long)
        w_prime = (best_20 - cp) * t_short
        mftp = cp * 0.97

        if cp < 50 or w_prime < 5000:
            continue

        result[target_date.isoformat()] = {
            "cp": round(cp, 1),
            "w_prime": round(w_prime, 0),
            "frc": round(w_prime, 0),
            "mftp": round(mftp, 1),
            "tte": round((w_prime / (cp * 0.05)) / 60, 1) if cp > 0 else None,
        }

    return result


def upsert_advanced_metrics(
    cur, user_id: str, load_metrics: dict, vo2max_by_date: dict, cp_data: dict
):
    """Upsert computed metrics into advanced_metric table."""
    all_dates = set(load_metrics.keys()) | set(vo2max_by_date.keys()) | set(cp_data.keys())

    for d_str in sorted(all_dates):
        load = load_metrics.get(d_str, {})
        evo2 = vo2max_by_date.get(d_str)
        cp = cp_data.get(d_str, {})

        cur.execute("""
            INSERT INTO advanced_metric (
                user_id, date, ctl, atl, tsb, acwr, ramp_rate,
                cp, w_prime, frc, mftp, tte, effective_vo2max, computed_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, NOW()
            )
            ON CONFLICT (user_id, date) DO UPDATE SET
                ctl = EXCLUDED.ctl,
                atl = EXCLUDED.atl,
                tsb = EXCLUDED.tsb,
                acwr = EXCLUDED.acwr,
                ramp_rate = EXCLUDED.ramp_rate,
                cp = COALESCE(EXCLUDED.cp, advanced_metric.cp),
                w_prime = COALESCE(EXCLUDED.w_prime, advanced_metric.w_prime),
                frc = COALESCE(EXCLUDED.frc, advanced_metric.frc),
                mftp = COALESCE(EXCLUDED.mftp, advanced_metric.mftp),
                tte = COALESCE(EXCLUDED.tte, advanced_metric.tte),
                effective_vo2max = COALESCE(
                    EXCLUDED.effective_vo2max, advanced_metric.effective_vo2max
                ),
                computed_at = NOW()
        """, (
            user_id, d_str,
            load.get("ctl"), load.get("atl"), load.get("tsb"),
            load.get("acwr"), load.get("ramp_rate"),
            cp.get("cp"), cp.get("w_prime"), cp.get("frc"),
            cp.get("mftp"), cp.get("tte"), evo2,
        ))


def run_compute(user_id: str):
    """Run a full metrics computation pass."""
    print(f"[metrics-compute] Computing advanced metrics for user {user_id}...")
    db = get_db()
    cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        ensure_advanced_metric_table(cur)
        daily_loads = fetch_daily_loads(cur, user_id)
        if not daily_loads:
            print("[metrics-compute] No daily load data found — skipping")
            db.commit()
            return

        load_metrics = compute_ewma_loads(daily_loads)
        vo2max_by_date = compute_effective_vo2max(cur, user_id)
        cp_data = compute_critical_power(cur, user_id)

        upsert_advanced_metrics(cur, user_id, load_metrics, vo2max_by_date, cp_data)
        db.commit()

        dates_computed = len(load_metrics)
        print(
            f"[metrics-compute] Done — {dates_computed} dates, "
            f"{len(vo2max_by_date)} VO2max points, "
            f"{'CP computed' if cp_data else 'no CP data'}"
        )
    except Exception as e:
        db.rollback()
        print(f"[metrics-compute] ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        cur.close()
        db.close()


def main():
    once_mode = "--once" in sys.argv
    print(
        f"[metrics-compute] Starting. "
        f"Mode: {'once' if once_mode else f'loop every {COMPUTE_INTERVAL_MINUTES}m'} "
        f"(timezone: {USER_TZ})"
    )
    run_compute(USER_ID)
    if not once_mode:
        while True:
            print(f"[metrics-compute] Sleeping {COMPUTE_INTERVAL_MINUTES}m...")
            time.sleep(COMPUTE_INTERVAL_MINUTES * 60)
            run_compute(USER_ID)


if __name__ == "__main__":
    main()
