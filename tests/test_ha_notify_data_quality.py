# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Tests for ha-notify.py fetch_data_quality summary."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "pulsecoach" / "rootfs" / "app" / "scripts"
)


class FakeCursor:
    """Minimal cursor returning a fixed data_quality_log result set."""

    def __init__(self, rows: list[dict[str, Any]] | Exception) -> None:
        self._rows = rows

    def execute(self, _query: str, _params: tuple[Any, ...]) -> None:
        if isinstance(self._rows, Exception):
            raise self._rows

    def fetchall(self) -> list[dict[str, Any]]:
        assert not isinstance(self._rows, Exception)
        return self._rows


def load_ha_notify(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test")
    monkeypatch.setenv("USER_TIMEZONE", "UTC")
    spec = importlib.util.spec_from_file_location(
        "ha_notify", SCRIPTS_DIR / "ha-notify.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ha_notify"] = module
    spec.loader.exec_module(module)
    return module


def _dq_row(check_name: str, severity: str, message: str,
            raw_value: float | None = None, d: str = "2025-01-04") -> dict:
    return {
        "check_name": check_name,
        "severity": severity,
        "message": message,
        "raw_value": raw_value,
        "d": d,
    }


def test_no_rows_is_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = load_ha_notify(monkeypatch)
    dq = mod.fetch_data_quality(FakeCursor([]), "user-1")
    assert dq["status"] == "ok"
    assert dq["issues"] == 0
    assert dq["missing_days"] == 0


def test_missing_table_returns_safe_default(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = load_ha_notify(monkeypatch)
    dq = mod.fetch_data_quality(FakeCursor(RuntimeError("no such table")), "user-1")
    assert dq["status"] == "ok"
    assert dq["issues"] == 0


def test_counts_missing_days_and_status(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = load_ha_notify(monkeypatch)
    rows = [
        _dq_row("missing_day", "warn", "No synced data for 2025-01-03"),
        _dq_row("missing_day", "warn", "No synced data for 2025-01-02"),
    ]
    dq = mod.fetch_data_quality(FakeCursor(rows), "user-1")
    assert dq["missing_days"] == 2
    assert dq["issues"] == 2
    assert dq["status"] == "warn"
    assert "2 day(s) missing" in dq["message"]


def test_stale_data_error_severity(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = load_ha_notify(monkeypatch)
    rows = [
        _dq_row("stale_data", "error",
                "Latest synced data is 10 day(s) old (last: 2025-01-01)",
                raw_value=10.0),
    ]
    dq = mod.fetch_data_quality(FakeCursor(rows), "user-1")
    assert dq["status"] == "error"
    assert dq["stale_days"] == 10
    assert "10 day(s) old" in dq["message"]


def test_field_gaps_collected(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = load_ha_notify(monkeypatch)
    rows = [
        _dq_row("missing_field", "info",
                "hrv missing on 3 of the last 14 day(s)", raw_value=3.0),
    ]
    dq = mod.fetch_data_quality(FakeCursor(rows), "user-1")
    assert dq["field_gaps"] == ["hrv missing on 3 of the last 14 day(s)"]
    # info-only -> status stays ok
    assert dq["status"] == "ok"
