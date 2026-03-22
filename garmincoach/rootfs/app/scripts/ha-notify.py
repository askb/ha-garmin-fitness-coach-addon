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
        SELECT COUNT(*) FROM daily_metric
        WHERE user_id = %s AND date >= CURRENT_DATE - INTERVAL '3 days'
          AND garmin_training_load > 50
    """, (user_id,))
    hard_days = cur.fetchone()[0]

    return {
        "daily": dm,
        "advanced": am,
        "consecutive_hard_days": hard_days,
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
        cur = db.cursor()

        data = get_latest_metrics(cur, user_id)
        dm = data["daily"]
        am = data["advanced"]

        if dm is None and am is None:
            print("[ha-notify] No data yet — skipping")
            return

        # --- Push sensor states ---

        # sensor.garmincoach_acwr
        acwr = am[4] if am else None
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
        tsb = am[3] if am else None
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
        ramp = am[5] if am else None
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
        ctl = am[1] if am else None
        push_sensor("sensor.garmincoach_ctl",
                    round(ctl, 1) if ctl else "unknown",
                    {"friendly_name": "GarminCoach Fitness (CTL)", "unit_of_measurement": "pts", "icon": "mdi:trending-up"})

        # sensor.garmincoach_atl (Fatigue/ATL)
        atl = am[2] if am else None
        push_sensor("sensor.garmincoach_atl",
                    round(atl, 1) if atl else "unknown",
                    {"friendly_name": "GarminCoach Fatigue (ATL)", "unit_of_measurement": "pts", "icon": "mdi:trending-down"})

        # sensor.garmincoach_body_battery
        bb = dm[3] if dm else None
        push_sensor("sensor.garmincoach_body_battery",
                    bb if bb is not None else "unknown",
                    {"friendly_name": "GarminCoach Body Battery", "unit_of_measurement": "%", "icon": "mdi:battery"})

        # sensor.garmincoach_sleep_debt
        sleep_debt = dm[5] if dm else None
        push_sensor("sensor.garmincoach_sleep_debt",
                    round(sleep_debt / 60, 1) if sleep_debt else 0,
                    {"friendly_name": "GarminCoach Sleep Debt", "unit_of_measurement": "h", "icon": "mdi:sleep"})

        print(f"[ha-notify] Sensors pushed — ACWR: {acwr}, Form: {tsb}, Risk: {risk_level}")

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

        if bb and bb < 20 and dm[6] and dm[6] > 60:  # low end BB, started high
            alerts.append(("🔋 Low Body Battery",
                          f"Body Battery is critically low ({bb}%). Recovery priority today.",
                          "gc_body_battery_low"))

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
