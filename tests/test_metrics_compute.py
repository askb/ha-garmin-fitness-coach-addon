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


# ---------------------------------------------------------------------------
# Engine parity: lock compute_ewma_loads to the app engine's canonical
# algorithm (packages/engine/src/strain/index.ts), the single source of
# truth. This reference is an independent re-port of the TS so the test is
# not circular: if either implementation drifts, the assertion fails.
# ---------------------------------------------------------------------------
def _engine_pmc_reference(daily_loads: dict) -> dict:
    """Independent port of computeDailyPMCSeries + computeTrainingLoads ramp."""
    if not daily_loads:
        return {}
    alpha_ctl = 2 / (42 + 1)
    alpha_atl = 2 / (7 + 1)
    dates = sorted(daily_loads)
    start = date.fromisoformat(dates[0])
    end = date.fromisoformat(dates[-1])
    series = []
    cur = start
    while cur <= end:
        series.append((cur.isoformat(), daily_loads.get(cur.isoformat(), 0.0)))
        cur += timedelta(days=1)
    loads = [load for _, load in series]
    ctl = loads[0]
    atl = loads[0]
    out: dict = {}
    for i, (d_str, load) in enumerate(series):
        if i > 0:
            ctl = alpha_ctl * load + (1 - alpha_ctl) * ctl
            atl = alpha_atl * load + (1 - alpha_atl) * atl
        tsb = ctl - atl
        aw = loads[max(0, i - 6):i + 1]
        cw = loads[max(0, i - 27):i + 1]
        acute = sum(aw) / max(1, len(aw))
        chronic = sum(cw) / max(1, len(cw))
        if chronic == 0:
            acwr = 2.0 if acute > 0 else 1.0
        else:
            acwr = acute / chronic
        prev = (date.fromisoformat(d_str) - timedelta(days=7)).isoformat()
        ramp = (ctl - out[prev]["ctl"]) if prev in out else None
        out[d_str] = {
            "ctl": round(ctl, 2),
            "atl": round(atl, 2),
            "tsb": round(tsb, 2),
            "acwr": round(acwr, 3),
            "ramp_rate": round(ramp, 2) if ramp is not None else None,
        }
    return out


class TestEngineParity:
    """Guarantee the Python compute matches the TS engine's canonical math."""

    def _series(self, n: int) -> dict:
        base = date(2025, 1, 1)
        loads = {}
        for i in range(n):
            # Deterministic, varied, with embedded rest days.
            loads[(base + timedelta(days=i)).isoformat()] = (
                0.0 if i % 6 == 5 else 40.0 + (i * 37) % 160
            )
        return loads

    def test_matches_engine_reference_full_series(self, metrics_compute):
        """Every day's CTL/ATL/TSB/ACWR/ramp matches the engine reference."""
        loads = self._series(120)
        got = metrics_compute.compute_ewma_loads(loads)
        ref = _engine_pmc_reference(loads)
        assert set(got) == set(ref)
        for d in ref:
            for key in ("ctl", "atl", "tsb", "acwr"):
                assert got[d][key] == pytest.approx(ref[d][key], abs=1e-6), (
                    f"{key} drift on {d}: {got[d][key]} != {ref[d][key]}"
                )
            assert got[d]["ramp_rate"] == (
                pytest.approx(ref[d]["ramp_rate"], abs=1e-6)
                if ref[d]["ramp_rate"] is not None
                else None
            )

    def test_uses_span_ewma_not_time_constant(self, metrics_compute):
        """CTL/ATL use alpha = 2/(N+1), not the drifted 1 - e^(-1/N)."""
        loads = {date(2025, 1, 1).isoformat(): 100.0}
        # Add one more day so an update is applied.
        loads[date(2025, 1, 2).isoformat()] = 0.0
        r = metrics_compute.compute_ewma_loads(loads)[date(2025, 1, 2).isoformat()]
        # span ATL after one 0-load day from seed 100: 100*(1-0.25) = 75.0
        assert r["atl"] == pytest.approx(75.0, abs=1e-6)
        # span CTL: 100*(1 - 2/43) ~= 95.35
        assert r["ctl"] == pytest.approx(100 * (1 - 2 / 43), abs=0.01)

    def test_acwr_is_rolling_mean_ratio_not_atl_over_ctl(self, metrics_compute):
        """ACWR uses 7d/28d rolling means, not the old ATL/CTL ratio."""
        base = date(2025, 1, 1)
        loads = {(base + timedelta(days=i)).isoformat(): 100.0 for i in range(40)}
        r = metrics_compute.compute_ewma_loads(loads)
        last = (base + timedelta(days=39)).isoformat()
        # Constant load => acute mean == chronic mean => ACWR == 1.0 exactly.
        assert r[last]["acwr"] == pytest.approx(1.0, abs=1e-9)

    def test_ramp_rate_is_absolute_points_per_week(self, metrics_compute):
        """Ramp rate is CTL(today) - CTL(7 days ago) in absolute points."""
        base = date(2025, 1, 1)
        loads = {(base + timedelta(days=i)).isoformat(): 80.0 for i in range(20)}
        r = metrics_compute.compute_ewma_loads(loads)
        day = (base + timedelta(days=14)).isoformat()
        prev = (base + timedelta(days=7)).isoformat()
        expected = round(r[day]["ctl"] - r[prev]["ctl"], 2)
        assert r[day]["ramp_rate"] == pytest.approx(expected, abs=1e-6)


class TestDecayConstants:
    """Verify EWMA smoothing constants match the engine's span convention."""

    def test_ctl_alpha_is_span_42(self, metrics_compute):
        # Engine uses alpha = 2 / (N + 1), not the time-constant 1 - e^(-1/N).
        assert metrics_compute.ALPHA_CTL == pytest.approx(2 / (42 + 1), abs=1e-12)

    def test_atl_alpha_is_span_7(self, metrics_compute):
        assert metrics_compute.ALPHA_ATL == pytest.approx(2 / (7 + 1), abs=1e-12)


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
        # Native path preserves component columns computed from raw signals.
        assert r["sleep_quantity_component"] == 80
        assert r["training_load_component"] == 70
        assert r["stress_component"] == 75

    def test_garmin_native_preserves_components_with_history(self, metrics_compute):
        """Native readiness keeps computed component values when raw signals exist."""
        rows = []
        for i in range(7):
            rows.append({
                "date": f"2025-01-{i + 1:02d}",
                "hrv": 60,
                "sleep_score": 80,
                "stress_score": 25,
                "resting_hr": 55,
                "body_battery_end": 70,
                "garmin_training_readiness": 21 if i == 6 else None,
                "garmin_training_readiness_level": "LOW" if i == 6 else None,
                "spo2": None,
                "respiration_rate": None,
                "skin_temp": None,
            })

        cur = _make_mock_cur(rows)
        result = metrics_compute.compute_readiness_score(cur, "user-1")
        r = result["2025-01-07"]

        assert r["score"] == 21
        assert r["zone"] == "low"
        assert r["source"] == "garmin_native"
        assert r["hrv_component"] is not None
        assert r["sleep_quantity_component"] is not None
        assert r["training_load_component"] is not None
        assert r["stress_component"] is not None
        assert r["resting_hr_component"] is not None

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
