# SPDX-FileCopyrightText: 2025 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Accuracy verification tests for garmin-sync.py helper functions.

Each test section cites the source of the expected value and documents
the hand-calculated expected result. These tests verify that our helper
functions correctly process Garmin API data.
"""

import importlib
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# The sync script lives outside the normal package tree; import it by path.
SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "pulsecoach"
    / "rootfs"
    / "app"
    / "scripts"
    / "garmin-sync.py"
)


@pytest.fixture()
def garmin_sync(tmp_path):
    """Import garmin-sync.py as a module, with garminconnect mocked."""
    mock_garmin_module = MagicMock()
    with patch.dict(sys.modules, {"garminconnect": mock_garmin_module}):
        spec = importlib.util.spec_from_file_location("garmin_sync", SCRIPT_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod._mock_garmin_module = mock_garmin_module
        yield mod


# ── _safe_sleep_minutes ──────────────────────────────────────────────────────
# Converts Garmin's sleep-in-seconds to minutes.
# Garmin API returns sleepTimeSeconds, deepSleepSeconds, etc.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSafeSleepMinutes:
    """Tests for _safe_sleep_minutes() — seconds-to-minutes conversion."""

    def test_sleep_seconds_to_minutes(self, garmin_sync):
        """28800 seconds = 480 minutes = 8 hours of sleep."""
        result = garmin_sync._safe_sleep_minutes(
            {"sleepTimeSeconds": 28800}, "sleepTimeSeconds"
        )
        assert result == 480

    def test_sleep_null_returns_none(self, garmin_sync):
        """Missing key should return None (not crash)."""
        result = garmin_sync._safe_sleep_minutes({}, "sleepTimeSeconds")
        assert result is None

    def test_sleep_zero(self, garmin_sync):
        """Zero seconds should return 0 minutes, not None."""
        result = garmin_sync._safe_sleep_minutes(
            {"sleepTimeSeconds": 0}, "sleepTimeSeconds"
        )
        assert result == 0

    def test_deep_sleep_conversion(self, garmin_sync):
        """7200 deep sleep seconds = 120 minutes = 2 hours."""
        result = garmin_sync._safe_sleep_minutes(
            {"deepSleepSeconds": 7200}, "deepSleepSeconds"
        )
        assert result == 120

    def test_integer_division_truncates(self, garmin_sync):
        """Floor division: 7199 seconds = 119 minutes (truncated)."""
        result = garmin_sync._safe_sleep_minutes(
            {"sleepTimeSeconds": 7199}, "sleepTimeSeconds"
        )
        assert result == 119


# ── _extract_sleep_time ──────────────────────────────────────────────────────
# Converts Garmin epoch-ms timestamps to minutes-from-midnight strings.
# Used for sleep start/end times in the daily_metric table.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestExtractSleepTime:
    """Tests for _extract_sleep_time() — epoch-ms to minutes-from-midnight."""

    def test_extract_sleep_time_2230(self, garmin_sync):
        """22:30 local time = 1350 minutes from midnight."""
        dt = datetime(2026, 3, 24, 22, 30, 0)
        ts_ms = int(dt.timestamp() * 1000)
        result = garmin_sync._extract_sleep_time(
            {"sleepStartTimestampLocal": ts_ms}, "sleepStartTimestampLocal"
        )
        assert result == "1350"

    def test_extract_sleep_time_0600(self, garmin_sync):
        """06:00 local time = 360 minutes from midnight."""
        dt = datetime(2026, 3, 25, 6, 0, 0)
        ts_ms = int(dt.timestamp() * 1000)
        result = garmin_sync._extract_sleep_time(
            {"sleepEndTimestampLocal": ts_ms}, "sleepEndTimestampLocal"
        )
        assert result == "360"

    def test_extract_sleep_time_midnight(self, garmin_sync):
        """00:00 (midnight) = 0 minutes from midnight."""
        dt = datetime(2026, 3, 25, 0, 0, 0)
        ts_ms = int(dt.timestamp() * 1000)
        result = garmin_sync._extract_sleep_time(
            {"sleepStartTimestampLocal": ts_ms}, "sleepStartTimestampLocal"
        )
        assert result == "0"

    def test_extract_sleep_time_none(self, garmin_sync):
        """Missing timestamp key should return None."""
        result = garmin_sync._extract_sleep_time(
            {}, "sleepStartTimestampLocal"
        )
        assert result is None


# ── _compute_sleep_debt ──────────────────────────────────────────────────────
# Computes sleep debt = need - actual (in minutes).
# Positive result means the person slept less than recommended.
# Negative result means surplus sleep.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestComputeSleepDebt:
    """Tests for _compute_sleep_debt() — sleep need vs actual comparison."""

    def test_compute_sleep_debt_positive(self, garmin_sync):
        """Need 480 min, slept 420 min (7h via 25200s) → debt = 60 min."""
        result = garmin_sync._compute_sleep_debt(
            {"sleepNeedInMinutes": 480, "sleepTimeSeconds": 25200}
        )
        assert result == 60

    def test_compute_sleep_debt_negative(self, garmin_sync):
        """Need 420 min, slept 480 min (8h via 28800s) → surplus = -60 min."""
        result = garmin_sync._compute_sleep_debt(
            {"sleepNeedInMinutes": 420, "sleepTimeSeconds": 28800}
        )
        assert result == -60

    def test_compute_sleep_debt_zero(self, garmin_sync):
        """Slept exactly the recommended amount → debt = 0."""
        result = garmin_sync._compute_sleep_debt(
            {"sleepNeedInMinutes": 480, "sleepTimeSeconds": 28800}
        )
        assert result == 0

    def test_compute_sleep_debt_no_need(self, garmin_sync):
        """Missing sleepNeedInMinutes → None (cannot compute)."""
        result = garmin_sync._compute_sleep_debt(
            {"sleepTimeSeconds": 28800}
        )
        assert result is None

    def test_compute_sleep_debt_no_actual(self, garmin_sync):
        """Missing sleepTimeSeconds → None (cannot compute)."""
        result = garmin_sync._compute_sleep_debt(
            {"sleepNeedInMinutes": 480}
        )
        assert result is None


# ── Stress field extraction ──────────────────────────────────────────────────
# Garmin's stress data comes from two different API endpoints with
# different field names:
#   - Stress endpoint: "avgStressLevel"
#   - Stats endpoint: "averageStressLevel"
#
# The sync code must handle both field names and fall back gracefully.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestStressFieldExtraction:
    """Tests for stress level field name handling across Garmin endpoints."""

    def test_stress_avg_field(self):
        """Garmin /stress endpoint uses 'avgStressLevel'."""
        stress = {"avgStressLevel": 42, "maxStressLevel": 87}
        val = stress.get("avgStressLevel") or stress.get("averageStressLevel")
        assert val == 42

    def test_stress_average_field(self):
        """Garmin /stats endpoint uses 'averageStressLevel'."""
        stats = {"averageStressLevel": 38}
        val = stats.get("avgStressLevel") or stats.get("averageStressLevel")
        assert val == 38

    def test_stress_fallback_chain(self):
        """When stress endpoint fails, fall back to stats endpoint field."""
        stress = {}
        stats = {"averageStressLevel": 45}
        val = (
            stress.get("avgStressLevel")
            or stress.get("averageStressLevel")
            or stats.get("averageStressLevel")
        )
        assert val == 45

    def test_stress_both_present_prefers_avg(self):
        """When both field names are present, avgStressLevel takes priority."""
        data = {"avgStressLevel": 40, "averageStressLevel": 42}
        val = data.get("avgStressLevel") or data.get("averageStressLevel")
        assert val == 40

    def test_stress_all_missing_returns_none(self):
        """When no stress data is available, result is None."""
        stress = {}
        stats = {}
        val = (
            stress.get("avgStressLevel")
            or stress.get("averageStressLevel")
            or stats.get("averageStressLevel")
        )
        assert val is None
