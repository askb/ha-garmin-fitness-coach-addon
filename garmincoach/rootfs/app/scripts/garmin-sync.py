#!/usr/bin/env python3
"""Garmin Connect sync script for GarminCoach HA Addon.

Pulls latest health data from Garmin Connect API and inserts into the
local database. Runs periodically via the s6 service manager.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta

try:
    from garminconnect import Garmin
except ImportError:
    print("ERROR: garminconnect not installed", file=sys.stderr)
    sys.exit(1)


DB_PATH = os.environ.get("DATABASE_URL", "file:/data/garmincoach.db").replace("file:", "")
GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL", "")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD", "")
TOKEN_DIR = "/data/garmin-tokens"


def get_client():
    """Authenticate with Garmin Connect, reusing saved session tokens."""
    os.makedirs(TOKEN_DIR, exist_ok=True)
    token_file = os.path.join(TOKEN_DIR, "session.json")

    client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)

    if os.path.exists(token_file):
        try:
            with open(token_file) as f:
                client.login(tokenstore=json.load(f))
            print("Authenticated with saved token")
            return client
        except Exception:
            print("Saved token expired, re-authenticating...")

    client.login()
    with open(token_file, "w") as f:
        json.dump(client.garth.dumps(), f)
    print("Authenticated with credentials, token saved")
    return client


def sync_daily_stats(client, db, date_str):
    """Sync daily health stats for a given date."""
    try:
        stats = client.get_stats(date_str)
        sleep = client.get_sleep_data(date_str)
        hrv = client.get_hrv_data(date_str)
        stress = client.get_stress_data(date_str)

        db.execute("""
            INSERT OR REPLACE INTO daily_metric (
                user_id, date, steps, calories, resting_hr, max_hr,
                total_sleep_minutes, deep_sleep_minutes, rem_sleep_minutes,
                light_sleep_minutes, awake_minutes, sleep_score,
                hrv, stress_score, body_battery_start, body_battery_end,
                floors_climbed, intensity_minutes, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "addon-user",
            date_str,
            stats.get("totalSteps"),
            stats.get("totalKilocalories"),
            stats.get("restingHeartRate"),
            stats.get("maxHeartRate"),
            sleep.get("dailySleepDTO", {}).get("sleepTimeSeconds", 0) // 60 if sleep else None,
            sleep.get("dailySleepDTO", {}).get("deepSleepSeconds", 0) // 60 if sleep else None,
            sleep.get("dailySleepDTO", {}).get("remSleepSeconds", 0) // 60 if sleep else None,
            sleep.get("dailySleepDTO", {}).get("lightSleepSeconds", 0) // 60 if sleep else None,
            sleep.get("dailySleepDTO", {}).get("awakeSleepSeconds", 0) // 60 if sleep else None,
            sleep.get("dailySleepDTO", {}).get("sleepScores", {}).get("overall", {}).get("value"),
            hrv.get("hrvSummary", {}).get("weeklyAvg") if hrv else None,
            stress.get("averageStressLevel") if stress else None,
            stats.get("bodyBatteryChargedValue"),
            stats.get("bodyBatteryDrainedValue"),
            stats.get("floorsAscended"),
            stats.get("intensityMinutesGoal"),
            datetime.utcnow().isoformat(),
        ))
        db.commit()
        print(f"  Synced daily stats for {date_str}")
    except Exception as e:
        print(f"  Failed to sync {date_str}: {e}", file=sys.stderr)


def sync_activities(client, db, days=7):
    """Sync recent activities."""
    try:
        activities = client.get_activities(0, days * 3)
        for act in activities:
            act_id = str(act.get("activityId", ""))
            db.execute("""
                INSERT OR IGNORE INTO activity (
                    user_id, garmin_activity_id, sport_type, sub_type,
                    started_at, duration_minutes, distance_meters,
                    avg_hr, max_hr, calories, avg_pace_sec_per_km,
                    aerobic_te, anaerobic_te, synced_at, raw_garmin_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "addon-user",
                act_id,
                act.get("activityType", {}).get("typeKey", "other"),
                act.get("activityType", {}).get("typeId", ""),
                act.get("startTimeLocal"),
                (act.get("duration", 0) or 0) / 60,
                act.get("distance"),
                act.get("averageHR"),
                act.get("maxHR"),
                act.get("calories"),
                act.get("averageSpeed"),
                act.get("aerobicTrainingEffect"),
                act.get("anaerobicTrainingEffect"),
                datetime.utcnow().isoformat(),
                json.dumps(act),
            ))
        db.commit()
        print(f"  Synced {len(activities)} activities")
    except Exception as e:
        print(f"  Failed to sync activities: {e}", file=sys.stderr)


def main():
    if not GARMIN_EMAIL or not GARMIN_PASSWORD:
        print("No Garmin credentials configured, skipping sync")
        return

    print(f"Starting Garmin sync at {datetime.utcnow().isoformat()}")
    client = get_client()
    db = sqlite3.connect(DB_PATH)

    today = datetime.utcnow().date()
    for days_ago in range(7):
        date_str = (today - timedelta(days=days_ago)).isoformat()
        sync_daily_stats(client, db, date_str)

    sync_activities(client, db, days=7)

    db.close()
    print("Garmin sync complete")


if __name__ == "__main__":
    main()
