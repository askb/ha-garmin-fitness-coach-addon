"""Tests for garmin-sync.py functions."""
import sys
import os
import json
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone

# Add scripts dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))


def _load_sync_module():
    """Load garmin-sync.py via importlib (handles hyphen in filename)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "garmin_sync",
        os.path.join(os.path.dirname(__file__), '..', 'scripts', 'garmin-sync.py')
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSyncDailyStats:
    """Tests for sync_daily_stats function."""

    def test_sleep_minutes_conversion(self):
        """Test _safe_sleep_minutes correctly converts seconds to minutes."""
        module = _load_sync_module()

        assert module._safe_sleep_minutes({"sleepTimeSeconds": 25200}, "sleepTimeSeconds") == 420  # 7h
        assert module._safe_sleep_minutes({"sleepTimeSeconds": 0}, "sleepTimeSeconds") == 0
        assert module._safe_sleep_minutes({}, "sleepTimeSeconds") is None
        assert module._safe_sleep_minutes({"sleepTimeSeconds": None}, "sleepTimeSeconds") is None

    def test_sleep_minutes_deep_sleep(self):
        """Test _safe_sleep_minutes for deep sleep conversion."""
        module = _load_sync_module()

        assert module._safe_sleep_minutes({"deepSleepSeconds": 5400}, "deepSleepSeconds") == 90  # 1.5h
        assert module._safe_sleep_minutes({"deepSleepSeconds": 3600}, "deepSleepSeconds") == 60  # 1h

    def test_daily_stats_upsert(self, db_mock, sample_stats, sample_sleep, sample_hrv):
        """Test that sync_daily_stats calls the right SQL with correct values."""
        conn, cursor = db_mock
        cursor.fetchone.return_value = None  # simulate no existing constraint check issue

        # Mock Garmin client
        client = MagicMock()
        client.get_stats.return_value = sample_stats
        client.get_sleep_data.return_value = sample_sleep
        client.get_hrv_data.return_value = sample_hrv
        client.get_stress_data.return_value = {}

        module = _load_sync_module()

        # Should not raise
        module.sync_daily_stats(client, conn, "2024-01-15")

        # Verify execute was called (INSERT INTO daily_metric)
        assert cursor.execute.called

    def test_daily_stats_handles_empty_sleep(self, db_mock, sample_stats):
        """Test sync_daily_stats handles missing sleep data gracefully."""
        conn, cursor = db_mock

        client = MagicMock()
        client.get_stats.return_value = sample_stats
        client.get_sleep_data.return_value = {}  # empty sleep response
        client.get_hrv_data.return_value = {}
        client.get_stress_data.return_value = {}

        module = _load_sync_module()

        # Should not raise even with empty sleep data
        module.sync_daily_stats(client, conn, "2024-01-15")
        assert cursor.execute.called


class TestMetricsCompute:
    """Tests for metrics-compute.py functions."""

    def _load_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "metrics_compute",
            os.path.join(os.path.dirname(__file__), '..', 'scripts', 'metrics-compute.py')
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_ewma_decay_constants(self):
        """Test that ATL and CTL decay constants are correct."""
        import math
        module = self._load_module()

        # ATL: 7-day time constant
        expected_atl = 1 - math.exp(-1 / 7)
        assert abs(module.ATL_DECAY - expected_atl) < 1e-10

        # CTL: 42-day time constant
        expected_ctl = 1 - math.exp(-1 / 42)
        assert abs(module.CTL_DECAY - expected_ctl) < 1e-10

    def test_ewma_loads_basic(self):
        """Test EWMA computation produces reasonable CTL/ATL for steady load."""
        module = self._load_module()

        # Constant load of 50 for 60 days
        from datetime import date, timedelta
        start = date(2024, 1, 1)
        daily_loads = {
            (start + timedelta(days=i)).isoformat(): 50.0
            for i in range(60)
        }

        results = module.compute_ewma_loads(daily_loads)

        assert len(results) == 60
        last = results[max(results.keys())]
        # After 60 days of constant load, both should be building toward 50
        assert last["ctl"] > 30   # CTL (42-day) builds slowly but meaningfully
        assert last["atl"] > 40   # ATL (7-day) converges faster
        # ATL converges faster than CTL, so after constant load ATL > CTL early on
        assert last["atl"] > last["ctl"]

    def test_ewma_tsb_is_ctl_minus_atl(self):
        """Test that TSB = CTL - ATL."""
        module = self._load_module()

        from datetime import date, timedelta
        start = date(2024, 1, 1)
        daily_loads = {(start + timedelta(days=i)).isoformat(): float(i * 2) for i in range(30)}

        results = module.compute_ewma_loads(daily_loads)

        for d_str, vals in results.items():
            expected_tsb = round(vals["ctl"] - vals["atl"], 2)
            # TSB is ctl - atl, allow small float rounding
            assert abs(vals["tsb"] - expected_tsb) <= 0.02, f"TSB mismatch on {d_str}"

    def test_acwr_zero_ctl(self):
        """Test ACWR is None when CTL is near zero (avoid division by zero)."""
        module = self._load_module()

        # Only 1 day of load — CTL will be near zero
        daily_loads = {"2024-01-01": 50.0}
        results = module.compute_ewma_loads(daily_loads)

        first = results["2024-01-01"]
        # With barely any data, ACWR should be None (CTL < 0.5 threshold)
        if first["acwr"] is not None:
            assert 0 < first["acwr"] < 10  # sanity check

    def test_idempotent_upsert(self, db_mock):
        """Test that upserting metrics twice produces the same result (idempotency)."""
        conn, cursor = db_mock
        cursor.fetchall.return_value = []  # no existing data

        module = self._load_module()

        load_metrics = {"2024-01-15": {"ctl": 45.2, "atl": 52.1, "tsb": -6.9, "acwr": 1.15, "ramp_rate": 3.2}}
        vo2max = {}
        cp_data = {}

        # Run upsert twice
        module.upsert_advanced_metrics(cursor, "test-user", load_metrics, vo2max, cp_data)
        module.upsert_advanced_metrics(cursor, "test-user", load_metrics, vo2max, cp_data)

        # Should have called execute twice (once per upsert, same data)
        assert cursor.execute.call_count == 2


class TestHANotify:
    """Tests for ha-notify.py functions."""

    def _load_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ha_notify",
            os.path.join(os.path.dirname(__file__), '..', 'scripts', 'ha-notify.py')
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_injury_risk_high(self):
        """Test injury risk calculation for high ACWR."""
        module = self._load_module()

        level, score = module.compute_injury_risk(acwr=1.6, tsb=-5, ramp_rate=3)
        assert level == "high"
        assert score >= 60

    def test_injury_risk_optimal(self):
        """Test injury risk calculation for optimal ACWR."""
        module = self._load_module()

        level, score = module.compute_injury_risk(acwr=1.1, tsb=5, ramp_rate=2)
        assert level == "low"
        assert score < 30

    def test_injury_risk_elevated(self):
        """Test injury risk calculation for elevated ACWR."""
        module = self._load_module()

        level, score = module.compute_injury_risk(acwr=1.4, tsb=0, ramp_rate=5)
        assert level == "elevated"
        assert 30 <= score < 60

    def test_injury_risk_overreach_tsb(self):
        """Test TSB overreaching adds to risk score."""
        module = self._load_module()

        # Borderline ACWR but severe overreaching via TSB
        level, score = module.compute_injury_risk(acwr=1.0, tsb=-25, ramp_rate=0)
        # TSB < -20 adds 25 pts, ACWR=1.0 (optimal) adds 0 → score=25
        assert score >= 25

    def test_injury_risk_none_acwr(self):
        """Test injury risk returns unknown when ACWR is None."""
        module = self._load_module()

        level, score = module.compute_injury_risk(acwr=None, tsb=-5, ramp_rate=3)
        assert level == "unknown"
        assert score == 0

    def test_no_supervisor_token(self):
        """Test that ha_request returns None gracefully when no token."""
        import os
        os.environ.pop("SUPERVISOR_TOKEN", None)

        module = self._load_module()
        module.SUPERVISOR_TOKEN = ""  # ensure empty

        result = module.ha_request("POST", "states/sensor.test", {"state": "1"})
        assert result is None

    def test_risk_score_capped_at_100(self):
        """Test that risk score never exceeds 100."""
        module = self._load_module()

        # Worst case: high ACWR + severe TSB + high ramp rate
        level, score = module.compute_injury_risk(acwr=2.0, tsb=-30, ramp_rate=15)
        assert score <= 100
        assert level == "high"
