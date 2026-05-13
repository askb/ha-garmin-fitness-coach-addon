# SPDX-FileCopyrightText: 2026 Anil Belur
# SPDX-License-Identifier: Apache-2.0
"""Pytest tests for metrics-compute.py.

Tests EWMA CTL/ATL/TSB/ACWR computation against synthetic fixture data
with known expected outputs. Verifies the computation engine produces
deterministic, accurate results.

Run with:
    pytest tests/test_metrics_compute.py -v
"""

import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add scripts to path for import
SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent / "pulsecoach" / "rootfs" / "app" / "scripts")
FIXTURES_DIR = str(Path(__file__).resolve().parent / "fixtures")


@pytest.fixture
def metrics_compute():
    """Import metrics-compute.py as a module."""
    if SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, SCRIPTS_DIR)
    with patch.dict("os.environ", {
        "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
        "USER_TIMEZONE": "UTC",
    }):
        # Reimport to pick up env changes
        if "metrics-compute" in sys.modules:
            del sys.modules["metrics-compute"]
        import importlib
        loader = importlib.machinery.SourceFileLoader(
            "metrics_compute",
            str(Path(SCRIPTS_DIR) / "metrics-compute.py"),
        )
        spec = importlib.util.spec_from_loader("metrics_compute", loader)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


@pytest.fixture
def synthetic_data():
    """Load 90-day synthetic fixture data."""
    fixture_path = Path(FIXTURES_DIR) / "synthetic_90day.json"
    with open(fixture_path) as f:
        return json.load(f)


class TestEWMAComputation:
    """Test EWMA CTL/ATL/TSB computation against synthetic fixture data."""

    def test_compute_ewma_loads_matches_fixture(self, metrics_compute, synthetic_data):
        """Verify compute_ewma_loads() output matches pre-computed expected values."""
        # Build daily_loads dict from fixture (date -> trimp, matches fixture expected values)
        daily_loads = {}
        for day in synthetic_data:
            daily_loads[day["date"]] = day["trimp"]

        results = metrics_compute.compute_ewma_loads(daily_loads)

        # Check last 30 days against expected fixture values
        tolerance = 0.5  # rounding + float precision
        for day in synthetic_data[60:]:
            d = day["date"]
            assert d in results, f"Missing date {d} in EWMA results"
            assert results[d]["ctl"] is not None
            assert results[d]["atl"] is not None
            assert results[d]["tsb"] is not None
            # Compare against pre-computed expected values from fixture
            assert abs(results[d]["ctl"] - day["expected_ctl"]) < tolerance, (
                f"CTL mismatch on {d}: got {results[d]['ctl']}, expected {day['expected_ctl']}"
            )
            assert abs(results[d]["atl"] - day["expected_atl"]) < tolerance, (
                f"ATL mismatch on {d}: got {results[d]['atl']}, expected {day['expected_atl']}"
            )
            assert abs(results[d]["tsb"] - day["expected_tsb"]) < tolerance, (
                f"TSB mismatch on {d}: got {results[d]['tsb']}, expected {day['expected_tsb']}"
            )

    def test_ewma_monotonic_properties(self, metrics_compute, synthetic_data):
        """Verify CTL has less day-to-day change than ATL (longer time constant)."""
        daily_loads = {d["date"]: d["garmin_training_load"] for d in synthetic_data}
        results = metrics_compute.compute_ewma_loads(daily_loads)

        dates = sorted(results.keys())
        ctl_values = [results[d]["ctl"] for d in dates]
        atl_values = [results[d]["atl"] for d in dates]

        # CTL (42-day) should have lower day-to-day changes than ATL (7-day)
        def avg_daily_change(values):
            return sum(abs(values[i] - values[i-1]) for i in range(1, len(values))) / (len(values) - 1)

        ctl_change = avg_daily_change(ctl_values[30:])
        atl_change = avg_daily_change(atl_values[30:])
        assert ctl_change < atl_change, "CTL should change more slowly than ATL"

    def test_ewma_empty_loads(self, metrics_compute):
        """Empty daily loads returns empty results."""
        assert metrics_compute.compute_ewma_loads({}) == {}

    def test_ewma_single_day(self, metrics_compute):
        """Single day load produces valid CTL/ATL."""
        results = metrics_compute.compute_ewma_loads({"2025-01-01": 100.0})
        assert len(results) == 1
        r = results["2025-01-01"]
        assert r["ctl"] > 0
        assert r["atl"] > 0
        assert r["acwr"] is not None or r["ctl"] <= 0.5

    def test_ewma_rest_day_reduces_atl(self, metrics_compute):
        """ATL should decrease faster than CTL on rest days."""
        loads = {}
        base = date(2025, 1, 1)
        # 30 days of training
        for i in range(30):
            loads[(base + timedelta(days=i)).isoformat()] = 100.0
        # 7 rest days
        for i in range(30, 37):
            loads[(base + timedelta(days=i)).isoformat()] = 0.0

        results = metrics_compute.compute_ewma_loads(loads)
        day30 = results[(base + timedelta(days=29)).isoformat()]
        day37 = results[(base + timedelta(days=36)).isoformat()]

        # After rest: ATL drops more than CTL
        ctl_drop = day30["ctl"] - day37["ctl"]
        atl_drop = day30["atl"] - day37["atl"]
        assert atl_drop > ctl_drop, "ATL should drop faster than CTL on rest"

    def test_acwr_danger_zone(self, metrics_compute):
        """ACWR > 1.3 should be flagged as danger zone after a load spike."""
        loads = {}
        base = date(2025, 1, 1)
        # 60 days moderate training
        for i in range(60):
            loads[(base + timedelta(days=i)).isoformat()] = 50.0
        # 7 days extreme spike
        for i in range(60, 67):
            loads[(base + timedelta(days=i)).isoformat()] = 300.0

        results = metrics_compute.compute_ewma_loads(loads)
        last_day = (base + timedelta(days=66)).isoformat()
        acwr = results[last_day]["acwr"]
        assert acwr is not None and acwr > 1.3, f"ACWR should spike above 1.3 after load spike, got {acwr}"


class TestDecayConstants:
    """Verify EWMA decay constants match Banister model."""

    def test_ctl_decay(self, metrics_compute):
        expected = 1 - math.exp(-1 / 42)
        assert abs(metrics_compute.CTL_DECAY - expected) < 1e-10

    def test_atl_decay(self, metrics_compute):
        expected = 1 - math.exp(-1 / 7)
        assert abs(metrics_compute.ATL_DECAY - expected) < 1e-10


class TestInjuryRisk:
    """Test injury risk computation from ha-notify.py."""

    @pytest.fixture
    def ha_notify(self):
        """Import ha-notify.py as a module."""
        if SCRIPTS_DIR not in sys.path:
            sys.path.insert(0, SCRIPTS_DIR)
        with patch.dict("os.environ", {
            "SUPERVISOR_TOKEN": "test",
            "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
            "USER_TIMEZONE": "UTC",
        }):
            import importlib
            loader = importlib.machinery.SourceFileLoader(
                "ha_notify",
                str(Path(SCRIPTS_DIR) / "ha-notify.py"),
            )
            spec = importlib.util.spec_from_loader("ha_notify", loader)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod

    def test_high_acwr_high_risk(self, ha_notify):
        level, score = ha_notify.compute_injury_risk(1.6, -25, 12)
        assert level == "high"
        assert score == 100  # 60 + 25 + 15 = 100

    def test_moderate_acwr_medium_risk(self, ha_notify):
        level, score = ha_notify.compute_injury_risk(1.35, -5, 3)
        assert level == "elevated"
        assert score == 30

    def test_low_acwr_low_risk(self, ha_notify):
        level, score = ha_notify.compute_injury_risk(1.0, 5, 2)
        assert level == "low"
        assert score == 0

    def test_none_inputs(self, ha_notify):
        level, score = ha_notify.compute_injury_risk(None, None, None)
        assert level == "unknown"
        assert score == 0


class TestReadinessZone:
    """Boundary tests for the readiness score → zone mapping."""

    def test_prime_zone(self, metrics_compute):
        assert metrics_compute._readiness_zone(80) == "prime"
        assert metrics_compute._readiness_zone(100) == "prime"

    def test_good_zone(self, metrics_compute):
        assert metrics_compute._readiness_zone(60) == "good"
        assert metrics_compute._readiness_zone(79) == "good"

    def test_moderate_zone(self, metrics_compute):
        assert metrics_compute._readiness_zone(40) == "moderate"
        assert metrics_compute._readiness_zone(59) == "moderate"

    def test_low_zone(self, metrics_compute):
        assert metrics_compute._readiness_zone(20) == "low"
        assert metrics_compute._readiness_zone(39) == "low"

    def test_poor_zone(self, metrics_compute):
        assert metrics_compute._readiness_zone(0) == "poor"
        assert metrics_compute._readiness_zone(19) == "poor"


def _make_mock_cur(rows):
    """Return a MagicMock psycopg2 cursor whose fetchall() yields ``rows``."""
    cur = MagicMock()
    cur.execute = MagicMock()
    cur.fetchall = MagicMock(return_value=rows)
    return cur


class TestComputeReadinessScore:
    """Tests for compute_readiness_score covering native + composite paths."""

    def test_empty_rows_returns_empty(self, metrics_compute):
        cur = _make_mock_cur([])
        assert metrics_compute.compute_readiness_score(cur, "user-1") == {}

    def test_garmin_native_passthrough(self, metrics_compute):
        """When Garmin readiness exists, score is used verbatim with that zone."""
        cur = _make_mock_cur([
            {
                "date": "2025-01-01",
                "hrv": 60,
                "sleep_score": 80,
                "stress_score": 25,
                "resting_hr": 55,
                "body_battery_end": 70,
                "garmin_training_readiness": 85,
                "garmin_training_readiness_level": "PRIME",
                "spo2": 97,
                "respiration_rate": 14,
                "skin_temp": 36.5,
            },
        ])
        result = metrics_compute.compute_readiness_score(cur, "user-1")
        assert "2025-01-01" in result
        r = result["2025-01-01"]
        assert r["score"] == 85
        assert r["zone"] == "prime"
        assert r["source"] == "garmin_native"
        # Native path leaves component columns null
        assert r["hrv_component"] is None
        assert r["sleep_quantity_component"] is None

    def test_buchheit_composite_when_native_absent(self, metrics_compute):
        """Composite path: sleep + body battery + stress drive the score."""
        rows = []
        for i in range(10):
            day = f"2025-01-{i + 1:02d}"
            rows.append({
                "date": day,
                "hrv": 55,
                "sleep_score": 75,
                "stress_score": 30,
                "resting_hr": 55,
                "body_battery_end": 65,
                "garmin_training_readiness": None,
                "garmin_training_readiness_level": None,
                "spo2": None,
                "respiration_rate": None,
                "skin_temp": None,
            })
        cur = _make_mock_cur(rows)
        result = metrics_compute.compute_readiness_score(cur, "user-1")
        # Need enough history before HRV/RHR components kick in (>=7 rows)
        last = result["2025-01-10"]
        assert last["source"] == "buchheit_composite"
        assert 0 <= last["score"] <= 100
        assert last["zone"] in {"prime", "good", "moderate", "low", "poor"}
        # Sleep is always populated when sleep_score is present
        assert last["sleep_quantity_component"] is not None

    def test_insufficient_history_skips_hrv_component(self, metrics_compute):
        """First few days without HRV history must not produce an HRV component."""
        rows = []
        for i in range(3):
            rows.append({
                "date": f"2025-01-{i + 1:02d}",
                "hrv": 55,
                "sleep_score": 75,
                "stress_score": 30,
                "resting_hr": 55,
                "body_battery_end": 65,
                "garmin_training_readiness": None,
                "garmin_training_readiness_level": None,
                "spo2": None,
                "respiration_rate": None,
                "skin_temp": None,
            })
        cur = _make_mock_cur(rows)
        result = metrics_compute.compute_readiness_score(cur, "user-1")
        # Day 1: only 1 HRV sample, history < 7 → no HRV component
        first = result.get("2025-01-01")
        assert first is not None
        assert first["hrv_component"] is None

    def test_no_signals_skips_day(self, metrics_compute):
        """A day with no usable inputs is omitted from results."""
        cur = _make_mock_cur([
            {
                "date": "2025-01-01",
                "hrv": None,
                "sleep_score": None,
                "stress_score": None,
                "resting_hr": None,
                "body_battery_end": None,
                "garmin_training_readiness": None,
                "garmin_training_readiness_level": None,
                "spo2": None,
                "respiration_rate": None,
                "skin_temp": None,
            },
        ])
        result = metrics_compute.compute_readiness_score(cur, "user-1")
        assert "2025-01-01" not in result


class TestFetchDailyLoads:
    """fetch_daily_loads must merge daily_metric and activity TRIMP correctly."""

    def test_uses_garmin_load_when_present(self, metrics_compute):
        cur = MagicMock()
        # First call: daily_metric query
        # Second call: activity TRIMP query
        cur.fetchall.side_effect = [
            [{"date": "2025-01-01", "load": 80.0}],
            [{"activity_date": "2025-01-01", "total_trimp": 120.0}],
        ]
        loads = metrics_compute.fetch_daily_loads(cur, "user-1")
        # When daily_metric has non-zero load, activity TRIMP is ignored
        assert loads == {"2025-01-01": 80.0}

    def test_falls_back_to_activity_trimp_when_load_zero(self, metrics_compute):
        cur = MagicMock()
        cur.fetchall.side_effect = [
            [{"date": "2025-01-01", "load": 0.0}],
            [{"activity_date": "2025-01-01", "total_trimp": 120.0}],
        ]
        loads = metrics_compute.fetch_daily_loads(cur, "user-1")
        assert loads == {"2025-01-01": 120.0}

    def test_empty_inputs_returns_empty(self, metrics_compute):
        cur = MagicMock()
        cur.fetchall.side_effect = [[], []]
        assert metrics_compute.fetch_daily_loads(cur, "user-1") == {}
