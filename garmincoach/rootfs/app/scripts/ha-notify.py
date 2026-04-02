#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""GarminCoach HA Notification Service.

Pushes sensor states and risk alerts to Home Assistant REST API.
Reads from PostgreSQL: daily_metric + advanced_metric tables.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 not installed", file=sys.stderr)
    sys.exit(1)

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass  # stdlib, always available

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres@127.0.0.1:5432/garmincoach")
USER_ID = os.environ.get("GARMIN_USER_ID", "seed-user-001")
HA_BASE_URL = os.environ.get("HA_BASE_URL", "http://supervisor/core")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
NOTIFY_INTERVAL_MINUTES = int(os.environ.get("NOTIFY_INTERVAL_MINUTES", "30"))


def ha_request(method: str, path: str, data: dict | None = None) -> dict | None:
    """Make a request to the HA REST API."""
    if not SUPERVISOR_TOKEN:
        print("[ha-notify] No SUPERVISOR_TOKEN — skipping HA API calls", file=sys.stderr)
        return None

    url = f"{HA_BASE_URL}/api/{path}"
    headers = {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode() if data else None

    try:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"[ha-notify] HA API error {e.code}: {e.reason}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[ha-notify] HA API request failed: {e}", file=sys.stderr)
        return None


def push_sensor(entity_id: str, state: str | float | int, attributes: dict) -> bool:
    """Push a sensor state to HA."""
    result = ha_request("POST", f"states/{entity_id}", {
        "state": str(state),
        "attributes": attributes,
    })
    return result is not None


def create_notification(title: str, message: str, notification_id: str) -> bool:
    """Create a persistent notification in HA."""
    return ha_request("POST", "services/persistent_notification/create", {
        "title": title,
        "message": message,
        "notification_id": notification_id,
    }) is not None


def get_latest_metrics(cur, user_id: str) -> dict:
    """Get latest daily_metric and advanced_metric rows."""
    cur.execute("""
        SELECT date, hrv, resting_hr, body_battery_end, stress_score,
               sleep_debt_minutes, body_battery_start
        FROM daily_metric
        WHERE user_id = %s
        ORDER BY date DESC LIMIT 1
    """, (user_id,))
    dm = cur.fetchone()

    cur.execute("""
        SELECT date, ctl, atl, tsb, acwr, ramp_rate, cp, mftp, effective_vo2max
        FROM advanced_metric
        WHERE user_id = %s
        ORDER BY date DESC LIMIT 1
    """, (user_id,))
    am = cur.fetchone()

    # Check consecutive hard days (last 3 days high strain)
    cur.execute("""
        SELECT COUNT(*) as count FROM daily_metric
        WHERE user_id = %s AND date >= CURRENT_DATE - INTERVAL '3 days'
          AND garmin_training_load > 50
    """, (user_id,))
    hard_days_row = cur.fetchone()
    hard_days = hard_days_row['count'] if hard_days_row else 0

    return {
        "daily": dm,
        "advanced": am,
        "consecutive_hard_days": hard_days,
    }


def recommend_workout(
    acwr: float | None,
    tsb: float | None,
    body_battery: int | None,
    stress_score: int | None,
    sleep_debt_minutes: int | None,
    consecutive_hard_days: int,
) -> dict:
    """Generate an AI-informed workout recommendation based on readiness signals.

    Uses evidence-based decision logic to replace Garmin Coach's rest-day
    suggestion, which suffers from a known sync desynchronization bug.

    Decision framework (Banister 1975, Hulin 2016, Buchheit 2014):
    - ACWR sweet spot: 0.8-1.3 (Hulin 2016)
    - TSB < -20: overreaching, need recovery (Meeusen 2013)
    - Body Battery < 30: insufficient energy reserves
    - Sleep debt > 2h: impaired adaptation (Halson 2014)
    - 3+ consecutive hard days: schedule recovery (Kellmann 2010)

    Returns dict with: is_rest_day, workout_type, intensity, duration_min,
    hr_zone_target, rationale.
    """
    # Default signals — conservative when data is missing
    bb = body_battery if body_battery is not None else 50
    sd_hrs = (sleep_debt_minutes / 60) if sleep_debt_minutes else 0
    stress = stress_score if stress_score is not None else 50

    # --- Rest day triggers (any one is sufficient) ---
    rest_reasons: list[str] = []

    if consecutive_hard_days >= 3:
        rest_reasons.append(
            f"{consecutive_hard_days} consecutive high-load days "
            "(Kellmann 2010: recovery required after 3+ hard days)"
        )

    if tsb is not None and tsb < -25:
        rest_reasons.append(
            f"TSB is {tsb:.1f} — deep overreach zone "
            "(Meeusen 2013: TSB < -25 indicates functional overreaching)"
        )

    if bb < 20:
        rest_reasons.append(
            f"Body Battery critically low ({bb}%) — insufficient energy reserves"
        )

    if sd_hrs > 3:
        rest_reasons.append(
            f"Sleep debt {sd_hrs:.1f}h — performance impaired "
            "(Mah 2011: >3h debt degrades reaction time and power output)"
        )

    if acwr is not None and acwr > 1.5:
        rest_reasons.append(
            f"ACWR {acwr:.2f} — high injury risk zone "
            "(Hulin 2016: ACWR >1.5 = 2-4x injury risk)"
        )

    if rest_reasons:
        return {
            "is_rest_day": True,
            "workout_type": "rest",
            "intensity": "none",
            "duration_min": 0,
            "hr_zone_target": 0,
            "rationale": "Rest day recommended. " + rest_reasons[0],
            "all_factors": rest_reasons,
        }

    # --- Active recovery triggers ---
    recovery_signals = 0
    if tsb is not None and tsb < -15:
        recovery_signals += 2
    if bb < 40:
        recovery_signals += 1
    if sd_hrs > 1.5:
        recovery_signals += 1
    if stress > 70:
        recovery_signals += 1
    if consecutive_hard_days >= 2:
        recovery_signals += 1
    if acwr is not None and acwr > 1.3:
        recovery_signals += 1

    if recovery_signals >= 3:
        return {
            "is_rest_day": False,
            "workout_type": "active_recovery",
            "intensity": "easy",
            "duration_min": 30,
            "hr_zone_target": 1,
            "rationale": (
                "Active recovery day — easy effort only. "
                f"Multiple recovery signals detected (TSB: {tsb}, "
                f"BB: {bb}%, stress: {stress})."
            ),
            "all_factors": [],
        }

    # --- Normal training day: select intensity based on form ---
    if tsb is not None and tsb > 5 and bb >= 70 and (acwr is None or acwr <= 1.2):
        # Fresh and ready — quality session
        return {
            "is_rest_day": False,
            "workout_type": "quality",
            "intensity": "hard",
            "duration_min": 60,
            "hr_zone_target": 4,
            "rationale": (
                f"Great day for intensity — TSB +{tsb:.0f} (fresh), "
                f"Body Battery {bb}%. Tempo, intervals, or race-pace work."
            ),
            "all_factors": [],
        }

    if tsb is not None and tsb >= -10 and bb >= 50:
        # Moderate form — aerobic development
        return {
            "is_rest_day": False,
            "workout_type": "aerobic",
            "intensity": "moderate",
            "duration_min": 45,
            "hr_zone_target": 2,
            "rationale": (
                f"Steady aerobic session — TSB {tsb:.0f}, Body Battery {bb}%. "
                "Zone 2 base building or moderate tempo."
            ),
            "all_factors": [],
        }

    # Default: easy day
    return {
        "is_rest_day": False,
        "workout_type": "easy",
        "intensity": "easy",
        "duration_min": 35,
        "hr_zone_target": 1,
        "rationale": (
            f"Easy effort today — form is neutral (TSB: {tsb}, BB: {bb}%). "
            "Keep it conversational pace."
        ),
        "all_factors": [],
    }


def compute_injury_risk(acwr: float | None, tsb: float | None, ramp_rate: float | None) -> tuple[str, int]:
    """Compute injury risk level. Returns (level, score_0_100)."""
    if acwr is None:
        return ("unknown", 0)

    risk_score = 0

    # ACWR contribution (Hulin 2016 guidelines)
    if acwr > 1.5:
        risk_score += 60  # High risk
    elif acwr > 1.3:
        risk_score += 30  # Elevated
    elif acwr < 0.8:
        risk_score += 10  # Under-training

    # TSB contribution (TrainingPeaks Form)
    if tsb is not None and tsb < -20:
        risk_score += 25  # Overreached
    elif tsb is not None and tsb < -10:
        risk_score += 10

    # Ramp rate contribution
    if ramp_rate is not None and abs(ramp_rate) > 10:
        risk_score += 15

    risk_score = min(100, risk_score)

    if risk_score >= 60:
        level = "high"
    elif risk_score >= 30:
        level = "elevated"
    elif risk_score >= 10:
        level = "moderate"
    else:
        level = "low"

    return (level, risk_score)


def run_notifications(user_id: str):
    """Push all sensor states and check for alerts."""
    print(f"[ha-notify] Running notification pass for user {user_id}...")

    db = None
    try:
        db = psycopg2.connect(DATABASE_URL)
        cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        data = get_latest_metrics(cur, user_id)
        dm = data["daily"]
        am = data["advanced"]

        if dm is None and am is None:
            print("[ha-notify] No data yet — skipping")
            return

        # --- Push sensor states ---

        # sensor.garmincoach_acwr
        acwr = am['acwr'] if am else None
        push_sensor("sensor.garmincoach_acwr",
                    round(acwr, 2) if acwr else "unknown",
                    {
                        "friendly_name": "GarminCoach ACWR",
                        "unit_of_measurement": "",
                        "icon": "mdi:run",
                        "status": "optimal" if acwr and 0.8 <= acwr <= 1.3 else
                                 ("caution" if acwr and acwr <= 1.5 else
                                  ("high_risk" if acwr and acwr > 1.5 else "unknown")),
                    })

        # sensor.garmincoach_form (TSB)
        tsb = am['tsb'] if am else None
        push_sensor("sensor.garmincoach_form",
                    round(tsb, 1) if tsb is not None else "unknown",
                    {
                        "friendly_name": "GarminCoach Form (TSB)",
                        "unit_of_measurement": "pts",
                        "icon": "mdi:chart-line",
                        "status": "fresh" if tsb and tsb > 5 else
                                 ("optimal" if tsb and tsb >= -10 else
                                  ("tired" if tsb and tsb >= -20 else "overreached")),
                    })

        # sensor.garmincoach_injury_risk
        ramp = am['ramp_rate'] if am else None
        risk_level, risk_score = compute_injury_risk(acwr, tsb, ramp)
        push_sensor("sensor.garmincoach_injury_risk",
                    risk_level,
                    {
                        "friendly_name": "GarminCoach Injury Risk",
                        "icon": "mdi:shield-alert",
                        "risk_score": risk_score,
                        "acwr": acwr,
                        "tsb": tsb,
                        "ramp_rate": ramp,
                    })

        # sensor.garmincoach_ctl (Fitness/CTL)
        ctl = am['ctl'] if am else None
        push_sensor("sensor.garmincoach_ctl",
                    round(ctl, 1) if ctl else "unknown",
                    {"friendly_name": "GarminCoach Fitness (CTL)", "unit_of_measurement": "pts", "icon": "mdi:trending-up"})

        # sensor.garmincoach_atl (Fatigue/ATL)
        atl = am['atl'] if am else None
        push_sensor("sensor.garmincoach_atl",
                    round(atl, 1) if atl else "unknown",
                    {"friendly_name": "GarminCoach Fatigue (ATL)", "unit_of_measurement": "pts", "icon": "mdi:trending-down"})

        # sensor.garmincoach_body_battery
        bb = dm['body_battery_end'] if dm else None
        push_sensor("sensor.garmincoach_body_battery",
                    bb if bb is not None else "unknown",
                    {"friendly_name": "GarminCoach Body Battery", "unit_of_measurement": "%", "icon": "mdi:battery"})

        # sensor.garmincoach_sleep_debt
        sleep_debt = dm['sleep_debt_minutes'] if dm else None
        push_sensor("sensor.garmincoach_sleep_debt",
                    round(sleep_debt / 60, 1) if sleep_debt else 0,
                    {"friendly_name": "GarminCoach Sleep Debt", "unit_of_measurement": "h", "icon": "mdi:sleep"})

        # sensor.garmincoach_workout_recommendation
        # AI-informed workout suggestion replacing Garmin Coach rest-day logic
        hard_days = data["consecutive_hard_days"]
        workout = recommend_workout(
            acwr=acwr,
            tsb=tsb,
            body_battery=dm['body_battery_end'] if dm else None,
            stress_score=dm['stress_score'] if dm else None,
            sleep_debt_minutes=dm['sleep_debt_minutes'] if dm else None,
            consecutive_hard_days=hard_days,
        )
        push_sensor("sensor.garmincoach_workout_recommendation",
                    workout["workout_type"],
                    {
                        "friendly_name": "GarminCoach Workout Recommendation",
                        "icon": "mdi:dumbbell" if not workout["is_rest_day"] else "mdi:sleep",
                        "is_rest_day": workout["is_rest_day"],
                        "intensity": workout["intensity"],
                        "duration_min": workout["duration_min"],
                        "hr_zone_target": workout["hr_zone_target"],
                        "rationale": workout["rationale"],
                        "all_factors": workout.get("all_factors", []),
                    })

        print(
            f"[ha-notify] Sensors pushed — ACWR: {acwr}, Form: {tsb}, "
            f"Risk: {risk_level}, Workout: {workout['workout_type']}"
        )

        # --- Alert notifications ---
        alerts = []

        if acwr and acwr > 1.5:
            alerts.append(("🔴 High Injury Risk — ACWR",
                          f"Your ACWR is {acwr:.2f} (>1.5 high risk zone per Hulin 2016). "
                          f"Consider reducing training load for 2-3 days.",
                          "gc_acwr_high"))
        elif acwr and acwr > 1.3:
            alerts.append(("🟡 Elevated ACWR",
                          f"ACWR is {acwr:.2f} — entering caution zone (>1.3). Monitor closely.",
                          "gc_acwr_caution"))

        if tsb is not None and tsb < -20:
            alerts.append(("😴 Overreaching Detected",
                          f"Training Stress Balance (Form) is {tsb:.1f} — below -20 indicates overreaching. "
                          f"Schedule a rest day or active recovery.",
                          "gc_tsb_overreach"))

        if sleep_debt and sleep_debt > 120:  # 2+ hours
            alerts.append(("💤 Sleep Debt Warning",
                          f"Sleep debt: {sleep_debt//60}h {sleep_debt%60}m. "
                          f"Prioritize sleep tonight for optimal recovery.",
                          "gc_sleep_debt"))

        if bb and bb < 20 and dm['body_battery_start'] and dm['body_battery_start'] > 60:  # low end BB, started high
            alerts.append(("🔋 Low Body Battery",
                          f"Body Battery is critically low ({bb}%). Recovery priority today.",
                          "gc_body_battery_low"))

        if hard_days >= 3:
            alerts.append(("🏋️ Consecutive Hard Training Days",
                          f"{hard_days} high-load days in the last 3 days. "
                          f"Consider a recovery or easy day to avoid overtraining.",
                          "gc_hard_days"))

        for title, msg, nid in alerts:
            create_notification(title, msg, nid)
            print(f"[ha-notify] Alert sent: {title}")

        cur.close()
    except Exception as e:
        print(f"[ha-notify] ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        if db:
            db.close()


def main():
    once_mode = "--once" in sys.argv
    print(f"[ha-notify] Starting. Mode: {'once' if once_mode else f'loop every {NOTIFY_INTERVAL_MINUTES}m'}")

    run_notifications(USER_ID)

    if not once_mode:
        while True:
            print(f"[ha-notify] Sleeping {NOTIFY_INTERVAL_MINUTES}m...")
            time.sleep(NOTIFY_INTERVAL_MINUTES * 60)
            run_notifications(USER_ID)


if __name__ == "__main__":
    main()
