#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Garmin Connect sync script for PulseCoach HA Addon.

Pulls latest health data from Garmin Connect API and inserts into the
local PostgreSQL database. Runs periodically via the s6 service manager.

Supports two auth modes:
  1. Saved tokens in /data/garmin-tokens/ (preferred, from generate-garmin-tokens.py)
  2. Email/password from environment variables (fallback)
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from garminconnect import Garmin
except ImportError:
    print("ERROR: garminconnect not installed", file=sys.stderr)
    sys.exit(1)

try:
    import psycopg2
except ImportError:
    print("ERROR: psycopg2 not installed", file=sys.stderr)
    sys.exit(1)


DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres@127.0.0.1:5432/pulsecoach")
GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL", "")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD", "")
TOKEN_DIR = "/data/garmin-tokens"
# Must match the userId used by the Next.js app (DEV_BYPASS_AUTH seed user)
USER_ID = os.environ.get("GARMIN_USER_ID", "seed-user-001")

# Timezone for date boundary calculations (e.g., "Australia/Brisbane")
_tz_name = os.environ.get("USER_TIMEZONE", "UTC")
try:
    USER_TZ = ZoneInfo(_tz_name)
except (KeyError, ValueError):
    print(f"WARNING: Invalid timezone '{_tz_name}', falling back to UTC", file=sys.stderr)
    USER_TZ = ZoneInfo("UTC")


def _user_today():
    """Get today's date in the user's configured timezone."""
    return datetime.now(USER_TZ).date()

SYNC_STATUS_FILE = os.path.join(TOKEN_DIR, ".sync_status")


def _write_sync_status(phase, detail="", progress=0):
    """Write sync progress to a shared status file for the auth server."""
    import json as _json
    os.makedirs(TOKEN_DIR, exist_ok=True)
    status = {
        "syncing": True,
        "phase": phase,
        "detail": detail,
        "progress": progress,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with open(SYNC_STATUS_FILE, "w") as f:
            _json.dump(status, f)
    except Exception:
        pass


def _clear_sync_status():
    """Clear sync status file when sync completes."""
    import json as _json
    status = {
        "syncing": False,
        "phase": "idle",
        "detail": "",
        "progress": 100,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with open(SYNC_STATUS_FILE, "w") as f:
            _json.dump(status, f)
    except Exception:
        pass


def _refresh_matview(db) -> None:
    """Refresh the daily_athlete_summary materialized view after sync."""
    cur = None
    try:
        cur = db.cursor()
        cur.execute("SELECT refresh_daily_athlete_summary()")
        db.commit()
        print("  Refreshed daily_athlete_summary materialized view")
    except Exception as e:
        db.rollback()
        print(f"  Matview refresh skipped: {e}", file=sys.stderr)
    finally:
        if cur is not None:
            cur.close()


def get_client():
    """Authenticate with Garmin Connect, preferring saved tokens."""
    os.makedirs(TOKEN_DIR, exist_ok=True)
    native_token_path = os.path.join(TOKEN_DIR, "garmin_tokens.json")
    oauth1_path = os.path.join(TOKEN_DIR, "oauth1_token.json")
    oauth2_path = os.path.join(TOKEN_DIR, "oauth2_token.json")

    # Migrate legacy garth tokens to garminconnect 0.3.x native format
    if not os.path.exists(native_token_path) and os.path.exists(oauth2_path):
        try:
            _migrate_garth_tokens(oauth2_path, native_token_path)
        except Exception as e:
            print(f"Token migration failed: {e}", file=sys.stderr)

    # Mode 1: Resume from saved tokens (garminconnect 0.3.x native format)
    if os.path.exists(native_token_path):
        try:
            client = Garmin(GARMIN_EMAIL or "token-user", GARMIN_PASSWORD or "")
            client.login(tokenstore=TOKEN_DIR)
            # Re-save tokens (refreshes if needed)
            try:
                client.client.dump(TOKEN_DIR)
            except Exception:
                pass
            print("Authenticated with saved tokens")
            return client
        except Exception as e:
            print(f"Saved tokens failed: {e}", file=sys.stderr)
            print("Will try credential login as fallback", file=sys.stderr)

    # Mode 2: Email/password login
    if GARMIN_EMAIL and GARMIN_PASSWORD:
        try:
            client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
            client.login()
            try:
                client.client.dump(TOKEN_DIR)
            except Exception:
                pass
            print("Authenticated with credentials, tokens saved")
            return client
        except Exception as e:
            print(f"Credential login failed: {e}", file=sys.stderr)

    return None


def _migrate_garth_tokens(oauth2_path, native_token_path):
    """Convert legacy garth OAuth2 tokens to garminconnect 0.3.x native format."""
    import base64

    with open(oauth2_path) as f:
        oauth2 = json.load(f)

    access_token = oauth2.get("access_token", "")
    refresh_token = oauth2.get("refresh_token", "")
    if not access_token:
        return

    # Extract client_id from JWT payload
    client_id = ""
    try:
        parts = access_token.split(".")
        payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
        jwt_data = json.loads(base64.b64decode(payload))
        client_id = jwt_data.get("client_id", "")
    except Exception:
        pass

    new_tokens = {
        "di_token": access_token,
        "di_refresh_token": refresh_token,
        "di_client_id": client_id,
    }
    with open(native_token_path, "w") as f:
        json.dump(new_tokens, f, indent=2)
    print(f"Migrated garth tokens to native format (client_id={client_id})")


def get_db():
    """Connect to PostgreSQL."""
    return psycopg2.connect(DATABASE_URL)


def _safe_sleep_minutes(sleep_dto, key):
    """Safely extract sleep seconds and convert to minutes."""
    val = sleep_dto.get(key)
    if val is None:
        return None
    return val // 60


def _extract_sleep_time(sleep_dto, key):
    """Extract sleep timestamp and convert to minutes-from-midnight string.

    Garmin *TimestampLocal fields store epoch milliseconds where the encoded
    UTC datetime represents the user's local wall-clock time. For example,
    a bedtime of 22:30 AEST is stored as the epoch-ms for 22:30 UTC (not
    the actual UTC instant). Using utcfromtimestamp recovers the intended
    hours and minutes without any system timezone dependency.
    """
    ts = sleep_dto.get(key)
    if ts is None:
        return None
    try:
        # Garmin "Local" timestamps encode local wall-clock time as UTC epoch
        dt = datetime.utcfromtimestamp(ts / 1000)
        minutes = dt.hour * 60 + dt.minute
        return str(minutes)
    except (ValueError, TypeError, OSError):
        return None


def _compute_sleep_debt(sleep_dto):
    """Compute sleep debt = need - actual (in minutes). Positive = deficit."""
    need = sleep_dto.get("sleepNeedInMinutes")
    actual_sec = sleep_dto.get("sleepTimeSeconds")
    if need is None or actual_sec is None:
        return None
    actual_min = actual_sec // 60
    return need - actual_min


def sync_daily_stats(client, db, date_str):
    """Sync daily health stats for a given date."""
    cur = db.cursor()
    try:
        stats = client.get_stats(date_str)
        sleep_data = client.get_sleep_data(date_str)
        hrv = client.get_hrv_data(date_str)
        stress = client.get_stress_data(date_str)

        # Fetch SpO2 and respiration data (gracefully handle API errors)
        spo2_data = None
        respiration_data = None
        try:
            spo2_data = client.get_spo2_data(date_str)
        except Exception as e:
            print(f"  SpO2 data unavailable for {date_str}: {e}")
        try:
            respiration_data = client.get_respiration_data(date_str)
        except Exception as e:
            print(f"  Respiration data unavailable for {date_str}: {e}")

        # Debug: log stress field names so we can verify data extraction
        stress_val = None
        if stress:
            stress_val = stress.get("avgStressLevel") or stress.get("averageStressLevel")
        if not stress_val and stats:
            stress_val = stats.get("averageStressLevel")
        if stress_val:
            print(f"  Stress score for {date_str}: {stress_val}")

        sleep_dto = sleep_data.get("dailySleepDTO", {}) if sleep_data else {}

        # Extract SpO2: prefer dedicated API, fall back to stats/sleep
        spo2_val = None
        if spo2_data:
            spo2_val = spo2_data.get("averageSpO2") or spo2_data.get("averageSpo2")
        if spo2_val is None and stats:
            spo2_val = stats.get("avgSpo2") or stats.get("averageSpo2")
        if spo2_val is None:
            spo2_val = sleep_dto.get("averageSpO2Value") if sleep_data else None

        # Extract respiration rate
        respiration_val = None
        if respiration_data:
            respiration_val = respiration_data.get("avgWakingRespirationValue") or respiration_data.get("avgSleepRespirationValue")
        if respiration_val is None and stats:
            respiration_val = stats.get("respirationAvg")

        # Compute data quality flag (percentage of key fields present)
        quality_fields = [
            stats.get("totalSteps"), stats.get("restingHeartRate"),
            _safe_sleep_minutes(sleep_dto, "sleepTimeSeconds"),
            sleep_dto.get("sleepScores", {}).get("overall", {}).get("value"),
            hrv.get("hrvSummary", {}).get("weeklyAvg") if hrv else None,
            stress_val, spo2_val,
        ]
        present = sum(1 for f in quality_fields if f is not None)
        data_quality = round(present / len(quality_fields) * 100)

        # Ensure unique constraint exists for upsert
        cur.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'daily_metric_user_date_uq'
                ) THEN
                    ALTER TABLE daily_metric
                        ADD CONSTRAINT daily_metric_user_date_uq
                        UNIQUE (user_id, date);
                END IF;
            END $$;
        """)

        cur.execute("""
            INSERT INTO daily_metric (
                user_id, date, steps, calories, resting_hr, max_hr,
                total_sleep_minutes, deep_sleep_minutes, rem_sleep_minutes,
                light_sleep_minutes, awake_minutes, sleep_score,
                hrv, stress_score, body_battery_start, body_battery_end,
                floors_climbed, intensity_minutes,
                sleep_start_time, sleep_end_time, sleep_need_minutes, sleep_debt_minutes,
                spo2, respiration_rate,
                synced_at, data_quality
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, date) DO UPDATE SET
                steps = EXCLUDED.steps,
                calories = EXCLUDED.calories,
                resting_hr = EXCLUDED.resting_hr,
                max_hr = EXCLUDED.max_hr,
                total_sleep_minutes = EXCLUDED.total_sleep_minutes,
                deep_sleep_minutes = EXCLUDED.deep_sleep_minutes,
                rem_sleep_minutes = EXCLUDED.rem_sleep_minutes,
                light_sleep_minutes = EXCLUDED.light_sleep_minutes,
                awake_minutes = EXCLUDED.awake_minutes,
                sleep_score = EXCLUDED.sleep_score,
                hrv = EXCLUDED.hrv,
                stress_score = EXCLUDED.stress_score,
                body_battery_start = EXCLUDED.body_battery_start,
                body_battery_end = EXCLUDED.body_battery_end,
                floors_climbed = EXCLUDED.floors_climbed,
                intensity_minutes = EXCLUDED.intensity_minutes,
                sleep_start_time = COALESCE(EXCLUDED.sleep_start_time, daily_metric.sleep_start_time),
                sleep_end_time = COALESCE(EXCLUDED.sleep_end_time, daily_metric.sleep_end_time),
                sleep_need_minutes = COALESCE(EXCLUDED.sleep_need_minutes, daily_metric.sleep_need_minutes),
                sleep_debt_minutes = COALESCE(EXCLUDED.sleep_debt_minutes, daily_metric.sleep_debt_minutes),
                spo2 = COALESCE(EXCLUDED.spo2, daily_metric.spo2),
                respiration_rate = COALESCE(EXCLUDED.respiration_rate, daily_metric.respiration_rate),
                synced_at = EXCLUDED.synced_at,
                data_quality = EXCLUDED.data_quality
        """, (
            USER_ID,
            date_str,
            stats.get("totalSteps"),
            stats.get("totalKilocalories"),
            stats.get("restingHeartRate"),
            stats.get("maxHeartRate"),
            _safe_sleep_minutes(sleep_dto, "sleepTimeSeconds"),
            _safe_sleep_minutes(sleep_dto, "deepSleepSeconds"),
            _safe_sleep_minutes(sleep_dto, "remSleepSeconds"),
            _safe_sleep_minutes(sleep_dto, "lightSleepSeconds"),
            _safe_sleep_minutes(sleep_dto, "awakeSleepSeconds"),
            sleep_dto.get("sleepScores", {}).get("overall", {}).get("value"),
            hrv.get("hrvSummary", {}).get("weeklyAvg") if hrv else None,
            (stress.get("avgStressLevel") or stress.get("averageStressLevel") or stats.get("averageStressLevel")) if stress else stats.get("averageStressLevel"),
            stats.get("bodyBatteryChargedValue"),
            stats.get("bodyBatteryDrainedValue"),
            stats.get("floorsAscended"),
            stats.get("intensityMinutesGoal"),
            _extract_sleep_time(sleep_dto, "sleepStartTimestampLocal"),
            _extract_sleep_time(sleep_dto, "sleepEndTimestampLocal"),
            sleep_dto.get("sleepNeedInMinutes"),
            _compute_sleep_debt(sleep_dto),
            spo2_val,
            respiration_val,
            datetime.now(timezone.utc).isoformat(),
            data_quality,
        ))
        db.commit()
        print(f"  Synced daily stats for {date_str}")
    except Exception as e:
        db.rollback()
        print(f"  Failed to sync {date_str}: {e}", file=sys.stderr)
    finally:
        cur.close()


def sync_activities(client, db, days=7):
    """Sync activities, fetching in batches of 100."""
    cur = db.cursor()
    try:
        # Ensure unique constraint exists for upsert
        cur.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'activity_garmin_id_uq'
                ) THEN
                    ALTER TABLE activity
                        ADD CONSTRAINT activity_garmin_id_uq
                        UNIQUE (garmin_activity_id);
                END IF;
            END $$;
        """)

        total = 0
        batch_size = 100
        start = 0
        while True:
            activities = client.get_activities(start, batch_size)
            if not activities:
                break

            for act in activities:
                act_id = str(act.get("activityId", ""))
                # Extract HR zone minutes (seconds → minutes)
                hr_zones = None
                z1 = act.get("hrTimeInZone_1")
                if z1 is not None:
                    hr_zones = json.dumps({
                        "zone1": round((act.get("hrTimeInZone_1", 0) or 0) / 60, 1),
                        "zone2": round((act.get("hrTimeInZone_2", 0) or 0) / 60, 1),
                        "zone3": round((act.get("hrTimeInZone_3", 0) or 0) / 60, 1),
                        "zone4": round((act.get("hrTimeInZone_4", 0) or 0) / 60, 1),
                        "zone5": round((act.get("hrTimeInZone_5", 0) or 0) / 60, 1),
                    })

                # Compute TRIMP from avg HR and duration
                avg_hr = act.get("averageHR")
                duration_min = (act.get("duration", 0) or 0) / 60
                trimp = None
                if avg_hr and duration_min > 0:
                    # Simplified TRIMP: duration * intensity factor
                    hr_ratio = avg_hr / 200.0  # Normalized intensity
                    trimp = round(duration_min * hr_ratio * 0.64 * (1.92 ** hr_ratio), 1)

                avg_cadence = (
                    act.get("averageRunningCadenceInStepsPerMinute")
                    or act.get("averageBikingCadenceInRevPerMinute")
                )
                max_cadence = (
                    act.get("maxRunningCadenceInStepsPerMinute")
                    or act.get("maxBikingCadenceInRevPerMinute")
                )

                cur.execute("""
                    INSERT INTO activity (
                        user_id, garmin_activity_id, sport_type, sub_type,
                        started_at, duration_minutes, distance_meters,
                        avg_hr, max_hr, calories, avg_pace_sec_per_km,
                        aerobic_te, anaerobic_te, hr_zone_minutes,
                        trimp_score, strain_score,
                        avg_power, normalized_power, max_power,
                        avg_cadence, max_cadence,
                        synced_at, raw_garmin_data
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (garmin_activity_id) DO UPDATE SET
                        hr_zone_minutes = COALESCE(EXCLUDED.hr_zone_minutes, activity.hr_zone_minutes),
                        trimp_score = COALESCE(EXCLUDED.trimp_score, activity.trimp_score),
                        strain_score = COALESCE(EXCLUDED.strain_score, activity.strain_score),
                        avg_power = COALESCE(EXCLUDED.avg_power, activity.avg_power),
                        normalized_power = COALESCE(EXCLUDED.normalized_power, activity.normalized_power),
                        max_power = COALESCE(EXCLUDED.max_power, activity.max_power),
                        avg_cadence = COALESCE(EXCLUDED.avg_cadence, activity.avg_cadence),
                        max_cadence = COALESCE(EXCLUDED.max_cadence, activity.max_cadence),
                        synced_at = EXCLUDED.synced_at,
                        raw_garmin_data = EXCLUDED.raw_garmin_data
                """, (
                    USER_ID,
                    act_id,
                    act.get("activityType", {}).get("typeKey", "other"),
                    act.get("activityType", {}).get("typeId", ""),
                    act.get("startTimeLocal"),
                    duration_min,
                    act.get("distance"),
                    avg_hr,
                    act.get("maxHR"),
                    act.get("calories"),
                    act.get("averageSpeed"),
                    act.get("aerobicTrainingEffect"),
                    act.get("anaerobicTrainingEffect"),
                    hr_zones,
                    trimp,
                    act.get("activityTrainingLoad"),
                    act.get("averagePower"),
                    act.get("normPower"),
                    act.get("maxPower"),
                    avg_cadence,
                    max_cadence,
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(act),
                ))
            db.commit()
            total += len(activities)
            print(f"  Synced batch: {len(activities)} activities (total: {total})")

            if len(activities) < batch_size:
                break
            start += batch_size

            # Incremental syncs: stop after enough recent activities
            if days <= 30 and total >= 50:
                break

        print(f"  Synced {total} activities total")
    except Exception as e:
        db.rollback()
        print(f"  Failed to sync activities: {e}", file=sys.stderr)
    finally:
        cur.close()


def backfill_from_raw_json(db):
    """Extract hr_zone_minutes, strain_score, trimp_score from stored raw_garmin_data."""
    cur = db.cursor()
    try:
        cur.execute("""
            SELECT id, raw_garmin_data, avg_hr, duration_minutes
            FROM activity
            WHERE user_id = %s
              AND raw_garmin_data IS NOT NULL
              AND (hr_zone_minutes IS NULL OR strain_score IS NULL)
        """, (USER_ID,))
        rows = cur.fetchall()
        if not rows:
            return

        updated = 0
        # Pre-fetch latest resting HR to avoid N+1 query in activity loop
        cached_resting_hr = 60  # fallback
        try:
            cur.execute("""
                SELECT resting_hr FROM daily_metric
                WHERE user_id = %s AND resting_hr IS NOT NULL
                ORDER BY date DESC LIMIT 1
            """, (USER_ID,))
            rhr_row = cur.fetchone()
            if rhr_row:
                cached_resting_hr = rhr_row[0] if isinstance(rhr_row, tuple) else rhr_row.get("resting_hr")
        except Exception:
            pass

        for row_id, raw_json, avg_hr, duration_min in rows:
            act = json.loads(raw_json) if isinstance(raw_json, str) else raw_json

            # Extract HR zones (seconds → minutes)
            hr_zones = None
            z1 = act.get("hrTimeInZone_1")
            if z1 is not None:
                hr_zones = json.dumps({
                    "zone1": round((act.get("hrTimeInZone_1", 0) or 0) / 60, 1),
                    "zone2": round((act.get("hrTimeInZone_2", 0) or 0) / 60, 1),
                    "zone3": round((act.get("hrTimeInZone_3", 0) or 0) / 60, 1),
                    "zone4": round((act.get("hrTimeInZone_4", 0) or 0) / 60, 1),
                    "zone5": round((act.get("hrTimeInZone_5", 0) or 0) / 60, 1),
                })

            # Garmin training load
            strain = act.get("activityTrainingLoad")

            # Compute TRIMP using Banister (1991) formula with resting HR
            trimp = None
            if avg_hr and duration_min and duration_min > 0:
                resting_hr = cached_resting_hr
                max_hr = 220 - 30  # conservative estimate; user profile ideal
                delta_ratio = (avg_hr - resting_hr) / max(1, max_hr - resting_hr)
                delta_ratio = max(0, min(1, delta_ratio))
                k = 1.92  # male constant (Banister)
                trimp = round(duration_min * delta_ratio * math.exp(k * delta_ratio), 1)

            if hr_zones or strain or trimp:
                cur.execute("""
                    UPDATE activity SET
                        hr_zone_minutes = COALESCE(%s, hr_zone_minutes),
                        strain_score = COALESCE(%s, strain_score),
                        trimp_score = COALESCE(%s, trimp_score)
                    WHERE id = %s
                """, (hr_zones, strain, trimp, row_id))
                updated += 1

        db.commit()
        if updated:
            print(f"  Backfilled {updated} activities with zones/strain/TRIMP")
    except Exception as e:
        db.rollback()
        print(f"  Backfill failed: {e}", file=sys.stderr)
    finally:
        cur.close()


def backfill_stress_and_sleep(client, db):
    """One-time backfill: re-fetch stress and sleep timing for dates with NULL values."""
    MARKER = os.path.join(TOKEN_DIR, ".stress_sleep_backfill_done")
    if os.path.exists(MARKER):
        return

    cur = db.cursor()
    try:
        cur.execute("""
            SELECT date FROM daily_metric
            WHERE user_id = %s
              AND (stress_score IS NULL OR sleep_start_time IS NULL)
            ORDER BY date DESC
            LIMIT 365
        """, (USER_ID,))
        dates = [row[0] for row in cur.fetchall()]
        if not dates:
            Path(MARKER).touch()
            return

        print(f"  Backfilling stress/sleep for {len(dates)} dates...")
        filled = 0
        for date_str in dates:
            try:
                stress = client.get_stress_data(date_str)
                sleep_data = client.get_sleep_data(date_str)
                stats = client.get_stats(date_str)
                sleep_dto = sleep_data.get("dailySleepDTO", {}) if sleep_data else {}

                stress_val = None
                if stress:
                    stress_val = stress.get("avgStressLevel") or stress.get("averageStressLevel")
                if not stress_val and stats:
                    stress_val = stats.get("averageStressLevel")

                sleep_start = _extract_sleep_time(sleep_dto, "sleepStartTimestampLocal")
                sleep_end = _extract_sleep_time(sleep_dto, "sleepEndTimestampLocal")
                sleep_need = sleep_dto.get("sleepNeedInMinutes")
                sleep_debt = _compute_sleep_debt(sleep_dto)

                cur.execute("""
                    UPDATE daily_metric SET
                        stress_score = COALESCE(%s, stress_score),
                        sleep_start_time = COALESCE(%s, sleep_start_time),
                        sleep_end_time = COALESCE(%s, sleep_end_time),
                        sleep_need_minutes = COALESCE(%s, sleep_need_minutes),
                        sleep_debt_minutes = COALESCE(%s, sleep_debt_minutes)
                    WHERE user_id = %s AND date = %s
                """, (stress_val, sleep_start, sleep_end, sleep_need, sleep_debt,
                      USER_ID, date_str))
                if stress_val or sleep_start:
                    filled += 1
            except Exception:
                pass  # skip individual date failures

        db.commit()
        Path(MARKER).touch()
        print(f"  Backfilled stress/sleep for {filled}/{len(dates)} dates")
    except Exception as e:
        db.rollback()
        print(f"  Stress/sleep backfill failed: {e}", file=sys.stderr)
    finally:
        cur.close()


def sync_vo2max(client, db, days=7):
    """Sync VO2max from Garmin's official max-metrics API, with computed fallback."""
    cur = db.cursor()
    try:
        # Ensure unique constraint exists for upsert
        cur.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'vo2max_estimate_user_date_sport_uq'
                ) THEN
                    ALTER TABLE vo2max_estimate
                        ADD CONSTRAINT vo2max_estimate_user_date_sport_uq
                        UNIQUE (user_id, date, sport);
                END IF;
            END $$;
        """)

        # Note: we no longer bulk-delete computed records. The per-date
        # fallback logic below uses ON CONFLICT to update only dates that
        # lack official Garmin data, preserving existing Uth estimates for
        # historical dates outside the current sync window.
        db.commit()

        cutoff = (_user_today() - timedelta(days=days))
        today = _user_today()

        # --- Primary: Garmin's official VO2max from max-metrics API ---
        garmin_count = 0
        try:
            d = cutoff
            while d <= today:
                date_str = d.isoformat()
                try:
                    metrics = client.get_max_metrics(date_str)
                except Exception:
                    d += timedelta(days=1)
                    continue

                if not metrics:
                    d += timedelta(days=1)
                    continue

                # get_max_metrics returns a list of metric entries
                entries = metrics if isinstance(metrics, list) else [metrics]
                for entry in entries:
                    vo2 = entry.get("generic", {}).get("vo2MaxPreciseValue") \
                        or entry.get("generic", {}).get("vo2MaxValue")
                    sport = "general"

                    if not vo2:
                        # Try cycling-specific
                        vo2 = entry.get("cycling", {}).get("vo2MaxPreciseValue") \
                            or entry.get("cycling", {}).get("vo2MaxValue")
                        if vo2:
                            sport = "cycling"

                    if not vo2:
                        continue

                    vo2 = float(vo2)
                    if vo2 < 10 or vo2 > 90:
                        continue

                    metric_date = entry.get("calendarDate", date_str)
                    cur.execute("""
                        INSERT INTO vo2max_estimate (
                            user_id, date, sport, value, source
                        ) VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (user_id, date, sport) DO UPDATE SET
                            value = EXCLUDED.value,
                            source = EXCLUDED.source
                    """, (USER_ID, metric_date, sport, round(vo2, 1), "garmin_official"))
                    garmin_count += 1

                if garmin_count % 50 == 0 and garmin_count > 0:
                    db.commit()
                d += timedelta(days=1)

            db.commit()
        except Exception as e:
            print(f"  Garmin max-metrics API failed: {e} — falling back to computed")
            db.rollback()

        # --- Fallback: computed VO2max only for dates missing official data ---
        # Only compute Uth estimates for specific dates where the Garmin API
        # returned no data, rather than the previous all-or-nothing approach.
        # This prevents overwriting good official data when the API partially fails.
        cur2 = db.cursor()
        try:
            # Find dates in the sync window that have no garmin_official record
            cur2.execute("""
                SELECT dm.date, dm.resting_hr
                FROM daily_metric dm
                WHERE dm.user_id = %s AND dm.date >= %s
                  AND dm.resting_hr IS NOT NULL AND dm.resting_hr > 30
                  AND dm.resting_hr <= 100
                  AND NOT EXISTS (
                      SELECT 1 FROM vo2max_estimate ve
                      WHERE ve.user_id = dm.user_id
                        AND ve.date = dm.date
                        AND ve.source = 'garmin_official'
                  )
                ORDER BY dm.date DESC
            """, (USER_ID, cutoff.isoformat()))

            # Use fetchmany() batching to handle large sync windows gracefully
            missing_dates: list[tuple] = []
            while True:
                rows = cur2.fetchmany(500)
                if not rows:
                    break
                missing_dates.extend(rows)

            uth_count = 0

            if missing_dates:
                # Fetch user age for age-predicted max HR
                cur2.execute("SELECT age FROM profile WHERE user_id = %s", (USER_ID,))
                age_row = cur2.fetchone()
                user_age = age_row[0] if age_row and age_row[0] else 35
                if not (age_row and age_row[0]):
                    print("  No age in profile — using default age=35")

                # Tanaka formula (2001) for HRmax: more accurate than 220-age
                # Ref: Tanaka H et al. Age-predicted maximal heart rate revisited.
                #      J Am Coll Cardiol. 2001;37(1):153-156.
                # 220-age has SD ±10-12 bpm; Tanaka reduces error significantly.
                age_predicted_max_hr = 208 - (0.7 * user_age)

                # Age-corrected Uth proportionality factor.
                # Original Uth et al. (2004) used 15.3 but this was validated ONLY
                # on well-trained men aged 21-51 (N=46).
                # Ref: PMC8443998 (2021) — factor decreases inversely with age:
                #   Age 20-35: ~15.3 (original)
                #   Age 35-45: ~13.5
                #   Age 45-55: ~12.5
                #   Age 55+:   ~11.5
                # Using 15.3 for a 45-year-old overestimates VO2max by ~18%.
                if user_age <= 35:
                    uth_factor = 15.3
                elif user_age <= 45:
                    uth_factor = 13.5
                elif user_age <= 55:
                    uth_factor = 12.5
                else:
                    uth_factor = 11.5

                print(f"  Uth fallback: age={user_age}, HRmax={age_predicted_max_hr:.0f}, factor={uth_factor}")

                for d_date, resting_hr in missing_dates:
                    vo2 = uth_factor * (age_predicted_max_hr / resting_hr)
                    if vo2 < 20 or vo2 > 90:
                        continue
                    cur2.execute("""
                        INSERT INTO vo2max_estimate (
                            user_id, date, sport, value, source
                        ) VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (user_id, date, sport) DO UPDATE SET
                            value = EXCLUDED.value, source = EXCLUDED.source
                    """, (USER_ID, d_date, "general", round(vo2, 1), "uth_method"))
                    uth_count += 1
                db.commit()

            print(
                f"  VO2max: {garmin_count} official Garmin records, "
                f"{uth_count} Uth fallback estimates "
                f"(for dates without official data)"
            )
        finally:
            cur2.close()
    except Exception as e:
        db.rollback()
        print(f"  Failed to sync VO2max: {e}", file=sys.stderr)
    finally:
        cur.close()


def main():
    has_tokens = (
        os.path.exists(os.path.join(TOKEN_DIR, "oauth1_token.json"))
        and os.path.exists(os.path.join(TOKEN_DIR, "oauth2_token.json"))
    )

    if not has_tokens and (not GARMIN_EMAIL or not GARMIN_PASSWORD):
        print("No Garmin tokens or credentials configured, skipping sync")
        _clear_sync_status()
        return

    print(f"Starting Garmin sync at {datetime.now(timezone.utc).isoformat()} (timezone: {USER_TZ})")
    _write_sync_status("starting", "Authenticating with Garmin...")
    client = get_client()
    if client is None:
        print("Failed to authenticate with Garmin, skipping sync", file=sys.stderr)
        _clear_sync_status()
        return

    # First sync: full history from 2019. Subsequent syncs: 7 days only.
    HISTORY_MARKER = os.path.join(TOKEN_DIR, ".initial_sync_done")
    if os.path.exists(HISTORY_MARKER):
        sync_days = 7
    else:
        # Calculate days from 2019-01-01 to today
        epoch = datetime(2019, 1, 1, tzinfo=timezone.utc).date()
        today = _user_today()
        sync_days = (today - epoch).days
        print(f"First sync — pulling {sync_days} days of history (from 2019-01-01)...")

    db = get_db()

    today = _user_today()
    for days_ago in range(sync_days):
        date_str = (today - timedelta(days=days_ago)).isoformat()
        _write_sync_status("daily_stats", f"Syncing {date_str}",
                           int((days_ago / sync_days) * 50))
        sync_daily_stats(client, db, date_str)

    # Garmin API: get_activities(start, limit) — fetch in batches of 100
    _write_sync_status("activities", "Syncing activities...", 50)
    sync_activities(client, db, days=sync_days)

    # Backfill computed fields from raw Garmin JSON
    _write_sync_status("backfill", "Computing zones & strain...", 80)
    backfill_from_raw_json(db)

    _write_sync_status("backfill_stress", "Backfilling stress & sleep timing...", 85)
    backfill_stress_and_sleep(client, db)

    _write_sync_status("vo2max", "Computing VO2max estimates...", 90)
    sync_vo2max(client, db, days=sync_days)

    # Refresh materialized view so all downstream queries see fresh data
    _write_sync_status("refresh", "Refreshing summary view...", 95)
    _refresh_matview(db)

    db.close()

    # Mark initial sync complete
    if not os.path.exists(HISTORY_MARKER):
        with open(HISTORY_MARKER, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())

    _clear_sync_status()
    print("Garmin sync complete")


if __name__ == "__main__":
    main()
