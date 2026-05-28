# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Tests for ha-actions.py Home Assistant event firing."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "pulsecoach" / "rootfs" / "app" / "scripts"
CURSOR_DIR = Path(__file__).resolve().parent / ".ha-actions-cursors"
SUPERVISOR_URL = "http://supervisor/core/api/events"


class FakeCursor:
    """Minimal psycopg2 cursor for audit-row polling."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.after = datetime.min.replace(tzinfo=timezone.utc)

    def execute(self, _query: str, params: tuple[datetime, ...]) -> None:
        self.after = params[0]

    def fetchall(self) -> list[dict[str, Any]]:
        return [row for row in self.rows if row["created_at"] > self.after]

    def close(self) -> None:
        return None


class FakeConnection:
    """Minimal psycopg2 connection for audit-row polling."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def cursor(self, **_kwargs: Any) -> FakeCursor:
        return FakeCursor(self.rows)

    def close(self) -> None:
        return None


def load_ha_actions(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]) -> types.ModuleType:
    """Import ha-actions.py and patch its DB connector to use fake rows."""
    spec = importlib.util.spec_from_file_location("ha_actions", SCRIPTS_DIR / "ha-actions.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ha_actions"] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.psycopg2, "connect", lambda *args, **kwargs: FakeConnection(rows))
    monkeypatch.setattr(module, "HA_BASE_URL", "http://supervisor/core")
    return module


@pytest.fixture()
def cursor_file() -> Path:
    """Provide a unique cursor path inside the repository tree."""
    CURSOR_DIR.mkdir(exist_ok=True)
    path = CURSOR_DIR / f"{uuid4()}.cursor"
    yield path
    if path.exists():
        path.unlink()
    try:
        CURSOR_DIR.rmdir()
    except OSError:
        pass


@pytest.fixture(autouse=True)
def ha_env(monkeypatch: pytest.MonkeyPatch, cursor_file: Path) -> None:
    """Set stable HA actions environment for each test."""
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    monkeypatch.setenv("HA_EVENTS_ENABLED", "true")
    monkeypatch.setenv("LOW_READINESS_THRESHOLD", "50")
    monkeypatch.setenv("HA_ACTIONS_CURSOR_FILE", str(cursor_file))
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test")


def row(kind: str, created_at: datetime, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a RecommendationAudit row fixture."""
    return {
        "id": str(uuid4()),
        "user_id": "seed-user-001",
        "date": "2026-05-27",
        "kind": kind,
        "payload": payload or {},
        "created_at": created_at,
    }


def register_event(requests_mock: Any, event_type: str, status_code: int = 200) -> None:
    """Register a Supervisor event endpoint."""
    requests_mock.post(f"{SUPERVISOR_URL}/{event_type}", status_code=status_code, json={"ok": True})


def test_audit_query_uses_drizzle_snake_case(monkeypatch):
    """Assert the poller queries the Drizzle-managed audit table."""
    module = load_ha_actions(monkeypatch, [])

    assert "FROM recommendation_audit" in module.AUDIT_QUERY
    assert "created_at > %s" in module.AUDIT_QUERY
    assert '"RecommendationAudit"' not in module.AUDIT_QUERY
    assert '"createdAt"' not in module.AUDIT_QUERY


def test_cursor_advances_after_processing_three_rows(monkeypatch, requests_mock, cursor_file):
    base = datetime.now(timezone.utc) - timedelta(minutes=30)
    rows = [
        row("recommendation", base + timedelta(minutes=1), {"recommendation": {"action": "rest", "reason": "Recover"}}),
        row("workout_complete", base + timedelta(minutes=2), {"workout_id": "w1", "deviation": {"minutes": 0}}),
        row("workout_missed", base + timedelta(minutes=3), {"planned_workout_id": "w2"}),
    ]
    for event_type in ("pulsecoach_recommendation", "pulsecoach_session_completed", "pulsecoach_session_missed"):
        register_event(requests_mock, event_type)
    module = load_ha_actions(monkeypatch, rows)

    stats = module.process_once(str(cursor_file))

    assert stats == module.ProcessStats(processed=3, fired=3, errors=0)
    assert cursor_file.read_text(encoding="utf-8").strip() == rows[2]["created_at"].isoformat()


def test_cursor_idempotency_skips_rows_at_saved_cursor(monkeypatch, requests_mock, cursor_file):
    created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    rows = [row("recommendation", created_at, {"recommendation": {"action": "workout", "reason": "Go"}})]
    cursor_file.write_text(f"{created_at.isoformat()}\n", encoding="utf-8")
    register_event(requests_mock, "pulsecoach_recommendation")
    module = load_ha_actions(monkeypatch, rows)

    stats = module.process_once(str(cursor_file))

    assert stats == module.ProcessStats(processed=0, fired=0, errors=0)
    assert requests_mock.call_count == 0


def test_recommendation_fires_recommendation_event(monkeypatch, requests_mock, cursor_file):
    rows = [row("recommendation", datetime.now(timezone.utc), {
        "recommendation": {"action": "workout", "intensity": "easy", "reason": "Fresh legs", "readiness": 72}
    })]
    register_event(requests_mock, "pulsecoach_recommendation")
    module = load_ha_actions(monkeypatch, rows)

    stats = module.process_once(str(cursor_file))

    assert stats.fired == 1
    assert requests_mock.last_request.json() == {
        "user_id": "seed-user-001",
        "date": "2026-05-27",
        "action": "workout",
        "intensity": "easy",
        "reason": "Fresh legs",
    }


def test_low_readiness_recommendation_fires_two_events(monkeypatch, requests_mock, cursor_file):
    rows = [row("recommendation", datetime.now(timezone.utc), {
        "recommendation": {"action": "rest", "intensity": "easy", "reason": "Readiness is low", "readiness": 35}
    })]
    register_event(requests_mock, "pulsecoach_recommendation")
    register_event(requests_mock, "pulsecoach_low_readiness")
    module = load_ha_actions(monkeypatch, rows)

    stats = module.process_once(str(cursor_file))

    assert stats == module.ProcessStats(processed=1, fired=2, errors=0)
    assert [req.url for req in requests_mock.request_history] == [
        f"{SUPERVISOR_URL}/pulsecoach_recommendation",
        f"{SUPERVISOR_URL}/pulsecoach_low_readiness",
    ]
    assert requests_mock.request_history[1].json() == {
        "user_id": "seed-user-001",
        "date": "2026-05-27",
        "readiness": 35,
        "reason": "Readiness is low",
    }


def test_workout_complete_fires_session_completed(monkeypatch, requests_mock, cursor_file):
    rows = [row("workout_complete", datetime.now(timezone.utc), {"workout_id": "daily-1", "deviation": {"duration_min": -5}})]
    register_event(requests_mock, "pulsecoach_session_completed")
    module = load_ha_actions(monkeypatch, rows)

    stats = module.process_once(str(cursor_file))

    assert stats.fired == 1
    assert requests_mock.last_request.json() == {
        "user_id": "seed-user-001",
        "date": "2026-05-27",
        "workout_id": "daily-1",
        "deviation": {"duration_min": -5},
    }


def test_workout_missed_fires_session_missed(monkeypatch, requests_mock, cursor_file):
    rows = [row("workout_missed", datetime.now(timezone.utc), {"planned_workout_id": "planned-1"})]
    register_event(requests_mock, "pulsecoach_session_missed")
    module = load_ha_actions(monkeypatch, rows)

    stats = module.process_once(str(cursor_file))

    assert stats.fired == 1
    assert requests_mock.last_request.json() == {
        "user_id": "seed-user-001",
        "date": "2026-05-27",
        "planned_workout_id": "planned-1",
    }


def test_supervisor_error_is_swallowed_and_next_iteration_runs(monkeypatch, requests_mock, cursor_file):
    base = datetime.now(timezone.utc) - timedelta(minutes=20)
    rows = [row("recommendation", base, {"recommendation": {"action": "rest", "reason": "Recover"}})]
    register_event(requests_mock, "pulsecoach_recommendation", status_code=500)
    register_event(requests_mock, "pulsecoach_session_completed")
    module = load_ha_actions(monkeypatch, rows)

    first = module.process_once(str(cursor_file))
    rows.append(row("workout_complete", base + timedelta(minutes=1), {"workout_id": "w3", "deviation": {}}))
    second = module.process_once(str(cursor_file))

    assert first == module.ProcessStats(processed=1, fired=0, errors=1)
    assert second == module.ProcessStats(processed=1, fired=1, errors=0)
    assert cursor_file.read_text(encoding="utf-8").strip() == rows[1]["created_at"].isoformat()


def test_events_disabled_advances_cursor_without_requests(monkeypatch, requests_mock, cursor_file):
    monkeypatch.setenv("HA_EVENTS_ENABLED", "false")
    rows = [row("recommendation", datetime.now(timezone.utc), {"recommendation": {"action": "workout", "reason": "Go"}})]
    register_event(requests_mock, "pulsecoach_recommendation")
    module = load_ha_actions(monkeypatch, rows)

    stats = module.process_once(str(cursor_file))

    assert stats == module.ProcessStats(processed=1, fired=0, errors=0)
    assert requests_mock.call_count == 0
    assert cursor_file.read_text(encoding="utf-8").strip() == rows[0]["created_at"].isoformat()
