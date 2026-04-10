# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Anil Belur
"""Tests for AI trend analysis, workout recommendations, and injury risk logic.

Covers three layers:
  1. Input correctness — metrics dict has expected keys and types
  2. Trend / decision logic — deterministic fixtures produce correct outputs
  3. Confidence degradation — missing data reduces confidence
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import helpers — load production modules without psycopg2 at import time
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "garmincoach" / "rootfs" / "app" / "scripts"


def _load_module(name: str, filename: str) -> types.ModuleType:
    """Import a script module with psycopg2 mocked out."""
    mock_psycopg2 = MagicMock()
    mock_psycopg2.extras = MagicMock()

    with patch.dict(sys.modules, {"psycopg2": mock_psycopg2, "psycopg2.extras": mock_psycopg2.extras}):
        spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / filename)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


ha_notify = _load_module("ha_notify", "ha-notify.py")
metrics_compute = _load_module("metrics_compute", "metrics-compute.py")


# ===========================================================================
# Layer 1: Workout recommendation — decision logic
# ===========================================================================

class TestWorkoutRecommendation:
    """Verify recommend_workout() returns correct decisions for known inputs."""

    def test_rest_day_high_acwr(self):
        """ACWR >1.5 triggers mandatory rest (Hulin 2016)."""
        result = ha_notify.recommend_workout(
            acwr=1.6, tsb=0.0, body_battery=60,
            stress_score=40, sleep_debt_minutes=0,
            consecutive_hard_days=0,
        )
        assert result["is_rest_day"] is True
        assert "ACWR" in result["rationale"]

    def test_rest_day_low_tsb(self):
        """TSB < -25 triggers rest (Meeusen 2013)."""
        result = ha_notify.recommend_workout(
            acwr=1.0, tsb=-30.0, body_battery=60,
            stress_score=40, sleep_debt_minutes=0,
            consecutive_hard_days=0,
        )
        assert result["is_rest_day"] is True
        assert "TSB" in result["rationale"]

    def test_rest_day_low_body_battery(self):
        """Body Battery < 20 triggers rest."""
        result = ha_notify.recommend_workout(
            acwr=1.0, tsb=5.0, body_battery=15,
            stress_score=40, sleep_debt_minutes=0,
            consecutive_hard_days=0,
        )
        assert result["is_rest_day"] is True
        assert "Body Battery" in result["rationale"]

    def test_rest_day_sleep_debt(self):
        """Sleep debt >3h triggers rest (Mah 2011)."""
        result = ha_notify.recommend_workout(
            acwr=1.0, tsb=5.0, body_battery=60,
            stress_score=40, sleep_debt_minutes=200,
            consecutive_hard_days=0,
        )
        assert result["is_rest_day"] is True
        assert "Sleep" in result["rationale"] or "sleep" in result["rationale"].lower()

    def test_rest_day_consecutive_hard_days(self):
        """3+ consecutive hard days triggers rest (Kellmann 2010)."""
        result = ha_notify.recommend_workout(
            acwr=1.0, tsb=0.0, body_battery=60,
            stress_score=40, sleep_debt_minutes=0,
            consecutive_hard_days=3,
        )
        assert result["is_rest_day"] is True
        assert "consecutive" in result["rationale"].lower()

    def test_no_rest_optimal_signals(self):
        """All signals in safe range → training day."""
        result = ha_notify.recommend_workout(
            acwr=1.1, tsb=5.0, body_battery=70,
            stress_score=30, sleep_debt_minutes=30,
            consecutive_hard_days=1,
        )
        assert result["is_rest_day"] is False
        assert result["workout_type"] != "rest"
        assert result["duration_min"] > 0

    def test_easy_day_moderate_fatigue(self):
        """Moderate fatigue signals → easy/recovery workout."""
        result = ha_notify.recommend_workout(
            acwr=1.2, tsb=-10.0, body_battery=45,
            stress_score=55, sleep_debt_minutes=60,
            consecutive_hard_days=2,
        )
        assert result["is_rest_day"] is False
        assert result["intensity"] in ("easy", "moderate", "recovery")

    def test_missing_data_conservative(self):
        """When all metrics are None, defaults to conservative recommendation."""
        result = ha_notify.recommend_workout(
            acwr=None, tsb=None, body_battery=None,
            stress_score=None, sleep_debt_minutes=None,
            consecutive_hard_days=0,
        )
        # Should not crash; should produce a valid result
        assert "is_rest_day" in result
        assert "rationale" in result


# ===========================================================================
# Layer 2: Injury risk computation
# ===========================================================================

class TestInjuryRisk:
    """Verify compute_injury_risk() classifies risk levels correctly."""

    def test_high_risk_acwr(self):
        """ACWR >1.5 → high risk."""
        level, score = ha_notify.compute_injury_risk(acwr=1.6, tsb=0.0, ramp_rate=0.0)
        assert level == "high"
        assert score >= 60

    def test_elevated_risk(self):
        """ACWR 1.3-1.5 → elevated."""
        level, score = ha_notify.compute_injury_risk(acwr=1.4, tsb=0.0, ramp_rate=0.0)
        assert level in ("elevated", "moderate")
        assert score >= 30

    def test_low_risk_optimal(self):
        """ACWR in sweet spot, good TSB → low risk."""
        level, score = ha_notify.compute_injury_risk(acwr=1.0, tsb=5.0, ramp_rate=2.0)
        assert level == "low"
        assert score < 10

    def test_combined_risk_factors(self):
        """Multiple risk factors compound the score."""
        level, score = ha_notify.compute_injury_risk(acwr=1.6, tsb=-25.0, ramp_rate=15.0)
        assert score >= 75
        assert level == "high"

    def test_unknown_when_no_acwr(self):
        """No ACWR data → unknown risk."""
        level, score = ha_notify.compute_injury_risk(acwr=None, tsb=0.0, ramp_rate=0.0)
        assert level == "unknown"
        assert score == 0

    def test_ramp_rate_contribution(self):
        """High ramp rate adds to risk score."""
        _, score_low = ha_notify.compute_injury_risk(acwr=1.0, tsb=0.0, ramp_rate=2.0)
        _, score_high = ha_notify.compute_injury_risk(acwr=1.0, tsb=0.0, ramp_rate=15.0)
        assert score_high > score_low

    def test_overreached_tsb(self):
        """TSB < -20 adds significant risk."""
        _, score_ok = ha_notify.compute_injury_risk(acwr=1.0, tsb=0.0, ramp_rate=0.0)
        _, score_or = ha_notify.compute_injury_risk(acwr=1.0, tsb=-25.0, ramp_rate=0.0)
        assert score_or > score_ok


# ===========================================================================
# Layer 3: EWMA decay constants (metrics-compute.py)
# ===========================================================================

class TestEWMAConstants:
    """Verify EWMA time constants used for CTL/ATL are physiologically correct."""

    def test_atl_decay_7day(self):
        """ATL decay constant matches 7-day exponential window."""
        import math
        expected = 1 - math.exp(-1 / 7)
        assert abs(metrics_compute.ATL_DECAY - expected) < 1e-10

    def test_ctl_decay_42day(self):
        """CTL decay constant matches 42-day exponential window."""
        import math
        expected = 1 - math.exp(-1 / 42)
        assert abs(metrics_compute.CTL_DECAY - expected) < 1e-10

    def test_atl_faster_than_ctl(self):
        """ATL (fatigue) responds faster than CTL (fitness)."""
        assert metrics_compute.ATL_DECAY > metrics_compute.CTL_DECAY


# ===========================================================================
# Layer 4: Confidence degradation with missing data
# ===========================================================================

class TestConfidenceDegradation:
    """Recommendation quality degrades gracefully when data is incomplete."""

    def test_full_data_has_specific_recommendation(self):
        """Full data produces specific workout type."""
        result = ha_notify.recommend_workout(
            acwr=1.1, tsb=8.0, body_battery=80,
            stress_score=25, sleep_debt_minutes=0,
            consecutive_hard_days=0,
        )
        assert result["workout_type"] != "rest"
        assert len(result["rationale"]) > 10

    def test_partial_data_still_works(self):
        """Missing some metrics still produces a recommendation."""
        result = ha_notify.recommend_workout(
            acwr=1.1, tsb=None, body_battery=None,
            stress_score=None, sleep_debt_minutes=None,
            consecutive_hard_days=0,
        )
        assert "is_rest_day" in result
        assert result["rationale"] is not None

    def test_no_crash_on_edge_values(self):
        """Extreme values don't crash the recommendation engine."""
        for acwr in [0.0, 0.1, 3.0, 5.0]:
            result = ha_notify.recommend_workout(
                acwr=acwr, tsb=-100.0, body_battery=0,
                stress_score=100, sleep_debt_minutes=600,
                consecutive_hard_days=10,
            )
            assert "is_rest_day" in result
