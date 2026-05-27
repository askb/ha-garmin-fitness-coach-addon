#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Fire Home Assistant events from PulseCoach recommendation audit rows."""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, NamedTuple, Sequence

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover - exercised only in stripped runtime images
    print("ERROR: psycopg2 not installed", file=sys.stderr)
    sys.exit(1)

try:
    import requests
except ImportError:  # pragma: no cover - exercised only in stripped runtime images
    print("ERROR: requests not installed", file=sys.stderr)
    sys.exit(1)

LOGGER = logging.getLogger("ha-actions")
DEFAULT_CURSOR_FILE = "/data/.ha-actions-cursor"
DEFAULT_DATABASE_URL = "postgresql://postgres@127.0.0.1:5432/pulsecoach"
HA_BASE_URL = os.environ.get("HA_BASE_URL", "http://supervisor/core").rstrip("/")

AUDIT_QUERY = """
    SELECT
        id,
        "userId" AS user_id,
        date,
        kind,
        payload,
        "createdAt" AS created_at
    FROM "RecommendationAudit"
    WHERE "createdAt" > %s
    ORDER BY "createdAt" ASC
"""


class ProcessStats(NamedTuple):
    """Summary counters for one polling pass."""

    processed: int
    fired: int
    errors: int


def configure_logging() -> None:
    """Configure process logging."""
    logging.basicConfig(level=logging.INFO, format="[ha-actions] %(levelname)s %(message)s")


def env_bool(name: str, default: bool) -> bool:
    """Read a boolean environment value."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    """Read an integer environment value."""
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        LOGGER.warning("Invalid %s=%r; using %s", name, value, default)
        return default


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO timestamp from the cursor file."""
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_iso(value: Any) -> str:
    """Convert database timestamp values to stable ISO strings."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return parse_timestamp(str(value)).isoformat()


def read_cursor(cursor_file: str) -> datetime:
    """Read the last processed timestamp, defaulting to one hour ago."""
    path = Path(cursor_file)
    if not path.exists():
        return datetime.now(timezone.utc) - timedelta(hours=1)
    try:
        return parse_timestamp(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fallback = datetime.now(timezone.utc) - timedelta(hours=1)
        LOGGER.error("Failed to read cursor %s: %s; using %s", cursor_file, exc, fallback.isoformat())
        return fallback


def write_cursor(cursor_file: str, created_at: Any) -> None:
    """Persist the cursor timestamp."""
    path = Path(cursor_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{to_iso(created_at)}\n", encoding="utf-8")


def get_db_connection() -> Any:
    """Connect to PostgreSQL using DB_* env vars, with DATABASE_URL fallback."""
    if any(os.environ.get(name) for name in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME")):
        return psycopg2.connect(
            host=os.environ.get("DB_HOST", "127.0.0.1"),
            port=env_int("DB_PORT", 5432),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", ""),
            dbname=os.environ.get("DB_NAME", "pulsecoach"),
        )
    return psycopg2.connect(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))


def normalize_payload(payload: Any) -> dict[str, Any]:
    """Return a JSON payload as a dictionary."""
    if isinstance(payload, dict):
        return payload
    if payload is None:
        return {}
    if isinstance(payload, str):
        import json

        try:
            loaded = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def get_nested(payload: Mapping[str, Any], *keys: str) -> Any:
    """Read a nested value from a mapping."""
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def payload_timestamp(payload: Mapping[str, Any]) -> datetime | None:
    """Return a planned workout timestamp from known payload keys, if present."""
    for key in (
        "planned_at",
        "plannedAt",
        "planned_start_at",
        "plannedStartAt",
        "scheduled_at",
        "scheduledAt",
        "start_at",
        "startAt",
    ):
        value = payload.get(key)
        if not value:
            continue
        try:
            return parse_timestamp(str(value))
        except ValueError:
            LOGGER.warning("Invalid workout_missed timestamp %s=%r", key, value)
            return None
    return None


def should_defer_missed_event(
    row: Mapping[str, Any],
    payload: Mapping[str, Any],
    missed_session_grace_min: int,
) -> bool:
    """Return true when a missed-session row is still inside its grace window."""
    planned_at = payload_timestamp(payload)
    if planned_at is None:
        return False
    ready_at = planned_at + timedelta(minutes=max(0, missed_session_grace_min))
    if datetime.now(timezone.utc) < ready_at:
        LOGGER.info(
            "Deferring workout_missed row %s until %s",
            row.get("id"),
            ready_at.isoformat(),
        )
        return True
    return False


def event_payload_for_row(
    row: Mapping[str, Any],
    low_readiness_threshold: int,
    missed_session_grace_min: int,
) -> tuple[list[tuple[str, dict[str, Any]]], bool]:
    """Build HA event payloads for one RecommendationAudit row.

    Returns ``(events, defer_cursor)``. ``defer_cursor`` is true only for
    workout_missed rows with a planned timestamp still inside the configured
    grace window, so the next poll can retry without losing the event.
    """
    payload = normalize_payload(row.get("payload"))
    kind = row.get("kind")
    user_id = row.get("user_id")
    date = str(row.get("date"))

    if kind == "recommendation":
        recommendation = get_nested(payload, "recommendation") or {}
        if not isinstance(recommendation, Mapping):
            recommendation = {}
        events = [(
            "pulsecoach_recommendation",
            {
                "user_id": user_id,
                "date": date,
                "action": recommendation.get("action"),
                "intensity": recommendation.get("intensity"),
                "reason": recommendation.get("reason"),
            },
        )]
        readiness = recommendation.get("readiness")
        try:
            readiness_value = int(readiness) if readiness is not None else None
        except (TypeError, ValueError):
            readiness_value = None
        if readiness_value is not None and readiness_value < low_readiness_threshold:
            events.append((
                "pulsecoach_low_readiness",
                {
                    "user_id": user_id,
                    "date": date,
                    "readiness": readiness_value,
                    "reason": recommendation.get("reason"),
                },
            ))
        return events, False

    if kind == "workout_complete":
        return [(
            "pulsecoach_session_completed",
            {
                "user_id": user_id,
                "date": date,
                "workout_id": payload.get("workout_id") or payload.get("workoutId"),
                "deviation": payload.get("deviation"),
            },
        )], False

    if kind == "workout_missed":
        if should_defer_missed_event(row, payload, missed_session_grace_min):
            return [], True
        return [(
            "pulsecoach_session_missed",
            {
                "user_id": user_id,
                "date": date,
                "planned_workout_id": payload.get("planned_workout_id") or payload.get("plannedWorkoutId"),
            },
        )], False

    return [], False


def fire_event(event_type: str, event_data: Mapping[str, Any], supervisor_token: str) -> bool:
    """Fire one event via the Home Assistant Supervisor API."""
    if not supervisor_token:
        LOGGER.warning("No SUPERVISOR_TOKEN; skipping %s", event_type)
        return False

    url = f"{HA_BASE_URL}/api/events/{event_type}"
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {supervisor_token}"},
            json=dict(event_data),
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        LOGGER.error("Failed to fire %s: %s", event_type, exc)
        return False

    LOGGER.info("Fired %s", event_type)
    return True


def fetch_rows(cursor: datetime) -> Sequence[Mapping[str, Any]]:
    """Fetch audit rows newer than the cursor."""
    db = get_db_connection()
    try:
        cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(AUDIT_QUERY, (cursor,))
            rows = cur.fetchall()
            return list(rows)
        finally:
            cur.close()
    finally:
        db.close()


def process_once(cursor_file: str | None = None) -> ProcessStats:
    """Process one audit batch and advance the cursor."""
    cursor_path = cursor_file or os.environ.get("HA_ACTIONS_CURSOR_FILE", DEFAULT_CURSOR_FILE)
    cursor = read_cursor(cursor_path)
    events_enabled = env_bool("HA_EVENTS_ENABLED", True)
    low_readiness_threshold = env_int("LOW_READINESS_THRESHOLD", 50)
    missed_session_grace_min = env_int("MISSED_SESSION_GRACE_MIN", 360)
    supervisor_token = os.environ.get("SUPERVISOR_TOKEN", "")

    rows = fetch_rows(cursor)
    fired = 0
    errors = 0
    processed = 0
    last_processed_at: Any | None = None

    if rows and not events_enabled:
        LOGGER.info("HA events disabled; advancing cursor without firing events")

    for row in rows:
        if not events_enabled:
            processed += 1
            last_processed_at = row["created_at"]
            continue

        events, defer_cursor = event_payload_for_row(
            row,
            low_readiness_threshold,
            missed_session_grace_min,
        )
        if defer_cursor:
            # The cursor is intentionally the only idempotency store. Stop at
            # the first deferred row so a future poll can fire it without
            # skipping over its timestamp.
            break
        processed += 1
        last_processed_at = row["created_at"]
        for event_type, event_data in events:
            if fire_event(event_type, event_data, supervisor_token):
                fired += 1
            else:
                errors += 1

    if last_processed_at is not None:
        write_cursor(cursor_path, last_processed_at)

    return ProcessStats(processed=processed, fired=fired, errors=errors)


def run_forever() -> None:
    """Run the long-lived poll loop."""
    poll_seconds = max(1, env_int("HA_ACTIONS_POLL_SECONDS", 60))
    cursor_file = os.environ.get("HA_ACTIONS_CURSOR_FILE", DEFAULT_CURSOR_FILE)
    LOGGER.info("Starting HA actions loop; poll=%ss cursor=%s", poll_seconds, cursor_file)

    next_summary_at = time.monotonic()
    totals = ProcessStats(processed=0, fired=0, errors=0)
    while True:
        try:
            stats = process_once(cursor_file)
        except Exception as exc:  # noqa: BLE001 - longrun must never crash
            LOGGER.error("Polling pass failed: %s", exc)
            stats = ProcessStats(processed=0, fired=0, errors=1)

        totals = ProcessStats(
            processed=totals.processed + stats.processed,
            fired=totals.fired + stats.fired,
            errors=totals.errors + stats.errors,
        )
        now = time.monotonic()
        if now >= next_summary_at:
            LOGGER.info(
                "processed %s rows, fired %s events, %s errors",
                totals.processed,
                totals.fired,
                totals.errors,
            )
            totals = ProcessStats(processed=0, fired=0, errors=0)
            next_summary_at = now + 60

        time.sleep(poll_seconds)


def main() -> None:
    """Entrypoint."""
    configure_logging()
    run_forever()


if __name__ == "__main__":
    main()
