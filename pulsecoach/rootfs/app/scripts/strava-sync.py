#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Anil Belur
"""Strava OAuth2 activity sync for PulseCoach.

Syncs activities from Strava API v3 into the shared activity table.
Uses OAuth2 refresh tokens for authentication. Activities are deduped
by strava_activity_id to coexist with Garmin-sourced activities.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import requests

# ── Configuration ────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres@127.0.0.1:5432/pulsecoach")
TOKEN_DIR = Path("/data/strava-tokens")
TOKEN_FILE = TOKEN_DIR / "strava_tokens.json"
STRAVA_API_BASE = "https://www.strava.com/api/v3"
STRAVA_TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"

USER_ID = "default"


def _load_tokens():
    """Load Strava tokens from disk."""
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return None


def _save_tokens(tokens):
    """Save Strava tokens to disk."""
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))


def refresh_access_token(client_id, client_secret, refresh_token):
    """Exchange refresh token for a new access token."""
    resp = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    tokens = {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": data["expires_at"],
        "athlete_id": data.get("athlete", {}).get("id"),
    }
    _save_tokens(tokens)
    return tokens


def get_valid_token(client_id, client_secret, refresh_token):
    """Return a valid access token, refreshing if expired."""
    tokens = _load_tokens()
    if tokens and tokens.get("expires_at", 0) > time.time() + 60:
        return tokens["access_token"]
    return refresh_access_token(client_id, client_secret, refresh_token)["access_token"]


def fetch_activities(access_token, after_epoch=None, per_page=100):
    """Fetch activities from Strava API."""
    params = {"per_page": per_page}
    if after_epoch:
        params["after"] = int(after_epoch)

    all_activities = []
    page = 1
    while True:
        params["page"] = page
        resp = requests.get(
            f"{STRAVA_API_BASE}/athlete/activities",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        all_activities.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
        time.sleep(1)  # Rate limiting

    return all_activities


def _map_sport_type(strava_type):
    """Map Strava activity type to normalized sport type."""
    mapping = {
        "Run": "running", "Trail Run": "trail_running",
        "Walk": "walking", "Hike": "hiking",
        "Ride": "cycling", "VirtualRide": "cycling",
        "Swim": "swimming", "Yoga": "yoga",
        "WeightTraining": "strength", "Workout": "other",
        "Rowing": "rowing", "Elliptical": "elliptical",
    }
    return mapping.get(strava_type, "other")


def _compute_trimp(duration_min, avg_hr, max_hr=None):
    """Estimate TRIMP from Strava activity (Banister simplified)."""
    if not avg_hr or not duration_min:
        return None
    resting_hr = 60  # Default estimate
    max_hr_est = max_hr or 190
    if max_hr_est <= resting_hr:
        return None
    hr_reserve = (avg_hr - resting_hr) / (max_hr_est - resting_hr)
    hr_reserve = max(0, min(1, hr_reserve))
    # Gender-neutral coefficient (1.67 avg of male 1.92 / female 1.67)
    return round(duration_min * hr_reserve * 1.67 * pow(2.718, 1.67 * hr_reserve), 1)


def ensure_strava_column(db):
    """Add strava_activity_id column to activity table if missing."""
    cur = db.cursor()
    cur.execute("""
        DO $$ BEGIN
            ALTER TABLE activity ADD COLUMN IF NOT EXISTS strava_activity_id BIGINT;
        EXCEPTION WHEN OTHERS THEN NULL;
        END $$;
    """)
    cur.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'activity_strava_id_uq'
            ) THEN
                ALTER TABLE activity
                    ADD CONSTRAINT activity_strava_id_uq
                    UNIQUE (strava_activity_id);
            END IF;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    # Add source_platform column for multi-source tracking
    cur.execute("""
        ALTER TABLE activity ADD COLUMN IF NOT EXISTS source_platform TEXT DEFAULT 'garmin';
    """)
    db.commit()


def sync_activities(db, activities):
    """Upsert Strava activities into the activity table."""
    cur = db.cursor()
    synced = 0
    for act in activities:
        strava_id = act["id"]
        sport = _map_sport_type(act.get("type", "Workout"))
        started_at = act.get("start_date")  # ISO 8601 UTC
        duration_min = round(act.get("elapsed_time", 0) / 60, 1)
        distance_m = act.get("distance", 0)
        avg_hr = act.get("average_heartrate")
        max_hr = act.get("max_heartrate")
        calories = act.get("calories") or act.get("kilojoules")

        avg_pace = None
        if distance_m and distance_m > 0 and duration_min > 0:
            avg_pace = round((duration_min * 60) / (distance_m / 1000), 1)

        trimp = _compute_trimp(duration_min, avg_hr, max_hr)

        try:
            cur.execute("""
                INSERT INTO activity (
                    user_id, strava_activity_id, sport_type,
                    started_at, duration_minutes, distance_meters,
                    avg_hr, max_hr, calories,
                    avg_pace_sec_per_km, trimp_score,
                    avg_power, avg_cadence,
                    source_platform, synced_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (strava_activity_id) DO UPDATE SET
                    sport_type = EXCLUDED.sport_type,
                    duration_minutes = EXCLUDED.duration_minutes,
                    distance_meters = EXCLUDED.distance_meters,
                    avg_hr = EXCLUDED.avg_hr,
                    max_hr = EXCLUDED.max_hr,
                    calories = EXCLUDED.calories,
                    avg_pace_sec_per_km = EXCLUDED.avg_pace_sec_per_km,
                    trimp_score = EXCLUDED.trimp_score,
                    avg_power = EXCLUDED.avg_power,
                    avg_cadence = EXCLUDED.avg_cadence,
                    synced_at = EXCLUDED.synced_at
            """, (
                USER_ID, strava_id, sport,
                started_at, duration_min, distance_m,
                avg_hr, max_hr, calories,
                avg_pace, trimp,
                act.get("average_watts"), act.get("average_cadence"),
                "strava", datetime.now(timezone.utc).isoformat(),
            ))
            synced += 1
        except Exception as e:
            print(f"  [strava-sync] Error syncing activity {strava_id}: {e}")
            db.rollback()
            continue

    db.commit()
    return synced


def main():
    """Main Strava sync entry point."""
    client_id = os.environ.get("STRAVA_CLIENT_ID", "").strip()
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("STRAVA_REFRESH_TOKEN", "").strip()

    if not all([client_id, client_secret, refresh_token]):
        print("[strava-sync] Strava credentials not configured, skipping.")
        return

    print("[strava-sync] Starting Strava activity sync...")

    try:
        access_token = get_valid_token(client_id, client_secret, refresh_token)
    except Exception as e:
        print(f"[strava-sync] Authentication failed: {e}")
        return

    db = psycopg2.connect(DATABASE_URL)
    try:
        ensure_strava_column(db)

        # Determine sync window: last 7 days for incremental, full history for first sync
        marker = TOKEN_DIR / ".strava_initial_sync_done"
        if marker.exists():
            after_epoch = time.time() - (7 * 86400)
            print("[strava-sync] Incremental sync (last 7 days)")
        else:
            after_epoch = None
            print("[strava-sync] Full initial sync")

        activities = fetch_activities(access_token, after_epoch)
        print(f"[strava-sync] Fetched {len(activities)} activities from Strava")

        if activities:
            count = sync_activities(db, activities)
            print(f"[strava-sync] Synced {count} activities to database")

        if not marker.exists():
            marker.touch()

    except Exception as e:
        print(f"[strava-sync] Sync error: {e}")
    finally:
        db.close()

    print("[strava-sync] Strava sync complete.")


if __name__ == "__main__":
    main()
