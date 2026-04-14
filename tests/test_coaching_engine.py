# SPDX-FileCopyrightText: 2026 Anil Belur
# SPDX-License-Identifier: Apache-2.0
"""Tests for PulseCoach workout recommendation engine.

Validates the deterministic coaching logic that produces daily
workout recommendations based on readiness signals.
"""

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Resolve path relative to repo root (works from any cwd)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_HA_NOTIFY_PATH = _REPO_ROOT / "pulsecoach" / "rootfs" / "app" / "scripts" / "ha-notify.py"


@pytest.fixture
def ha_notify():
    """Import ha-notify module with mocked dependencies."""
    with patch.dict("os.environ", {
        "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
        "SUPERVISOR_TOKEN": "test-token",
    }):
        # Remove cached module if present
        mod_name = "ha-notify"
        if mod_name in sys.modules:
            del sys.modules[mod_name]

        spec = importlib.util.spec_from_file_location(
            mod_name,
            str(_HA_NOTIFY_PATH),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return mod


class TestRestDayTriggers:
    """Test conditions that trigger a rest day recommendation."""

    def test_low_readiness_triggers_rest(self, ha_notify):
        """Readiness < 25 should recommend rest."""
        result = ha_notify.recommend_workout(
            acwr=1.0, tsb=0, body_battery=50, stress_score=40,
            sleep_debt_minutes=0, consecutive_hard_days=0,
            readiness_score=20, garmin_training_status=None,
        )
        assert result["is_rest_day"] is True
        assert result["workout_type"] == "rest"
        assert "Readiness" in result["rationale"]

    def test_overreaching_status_triggers_rest(self, ha_notify):
        """Garmin OVERREACHING status should recommend rest."""
        result = ha_notify.recommend_workout(
            acwr=1.0, tsb=-5, body_battery=60, stress_score=40,
            sleep_debt_minutes=0, consecutive_hard_days=0,
            readiness_score=50, garmin_training_status="OVERREACHING",
        )
        assert result["is_rest_day"] is True
        assert "OVERREACHING" in result["rationale"]

    def test_high_acwr_triggers_rest(self, ha_notify):
        """ACWR > 1.5 should recommend rest."""
        result = ha_notify.recommend_workout(
            acwr=1.7, tsb=-10, body_battery=50, stress_score=50,
            sleep_debt_minutes=0, consecutive_hard_days=1,
            readiness_score=50,
        )
        assert result["is_rest_day"] is True
        assert "ACWR" in result["rationale"]

    def test_deep_overreach_triggers_rest(self, ha_notify):
        """TSB < -25 should recommend rest."""
        result = ha_notify.recommend_workout(
            acwr=1.0, tsb=-30, body_battery=50, stress_score=50,
            sleep_debt_minutes=0, consecutive_hard_days=1,
            readiness_score=50,
        )
        assert result["is_rest_day"] is True
        assert "TSB" in result["rationale"]

    def test_consecutive_hard_days_triggers_rest(self, ha_notify):
        """3+ consecutive hard days should recommend rest."""
        result = ha_notify.recommend_workout(
            acwr=1.0, tsb=0, body_battery=60, stress_score=40,
            sleep_debt_minutes=0, consecutive_hard_days=3,
            readiness_score=60,
        )
        assert result["is_rest_day"] is True
        assert "consecutive" in result["rationale"]


class TestActiveRecovery:
    """Test conditions that trigger active recovery."""

    def test_multiple_recovery_signals(self, ha_notify):
        """3+ recovery signals should recommend active recovery."""
        result = ha_notify.recommend_workout(
            acwr=1.35, tsb=-18, body_battery=35, stress_score=75,
            sleep_debt_minutes=120, consecutive_hard_days=2,
            readiness_score=35,
        )
        assert result["workout_type"] == "active_recovery"
        assert result["intensity"] == "easy"
        assert result["duration_min"] == 30

    def test_low_readiness_adds_recovery_signal(self, ha_notify):
        """Readiness < 40 should add to recovery signals."""
        # Without low readiness: 2 signals (TSB=-18, consecutive=2)
        result_high = ha_notify.recommend_workout(
            acwr=1.0, tsb=-18, body_battery=50, stress_score=50,
            sleep_debt_minutes=0, consecutive_hard_days=2,
            readiness_score=60,
        )
        # With low readiness: 3 signals (TSB=-18, consecutive=2, readiness=35)
        result_low = ha_notify.recommend_workout(
            acwr=1.0, tsb=-18, body_battery=50, stress_score=50,
            sleep_debt_minutes=0, consecutive_hard_days=2,
            readiness_score=35,
        )
        # Low readiness should push toward easier workout than high readiness
        intensity_order = {"rest": 0, "active_recovery": 1, "easy": 2, "aerobic": 3, "quality": 4}
        low_intensity = intensity_order.get(result_low["workout_type"], 2)
        high_intensity = intensity_order.get(result_high["workout_type"], 2)
        assert low_intensity <= high_intensity, (
            f"Low readiness should not recommend harder workout: "
            f"{result_low['workout_type']} vs {result_high['workout_type']}"
        )


class TestQualitySession:
    """Test conditions for quality/hard workout recommendations."""

    def test_fresh_and_ready(self, ha_notify):
        """High readiness + positive TSB + good BB = quality session."""
        result = ha_notify.recommend_workout(
            acwr=1.0, tsb=10, body_battery=80, stress_score=30,
            sleep_debt_minutes=0, consecutive_hard_days=0,
            readiness_score=85,
        )
        assert result["workout_type"] == "quality"
        assert result["intensity"] == "hard"
        assert result["hr_zone_target"] == 4

    def test_peaking_status_enables_quality(self, ha_notify):
        """Garmin PEAKING status should enable quality workout."""
        result = ha_notify.recommend_workout(
            acwr=1.0, tsb=0, body_battery=70, stress_score=40,
            sleep_debt_minutes=0, consecutive_hard_days=0,
            readiness_score=65, garmin_training_status="PEAKING",
        )
        assert result["workout_type"] == "quality"
        assert "PEAKING" in result["rationale"]

    def test_productive_status_enables_quality(self, ha_notify):
        """Garmin PRODUCTIVE status should enable quality workout."""
        result = ha_notify.recommend_workout(
            acwr=1.1, tsb=-2, body_battery=65, stress_score=45,
            sleep_debt_minutes=0, consecutive_hard_days=0,
            readiness_score=60, garmin_training_status="PRODUCTIVE",
        )
        assert result["workout_type"] == "quality"

    def test_high_readiness_overrides_neutral_tsb(self, ha_notify):
        """High readiness (>=70) should allow quality even with neutral TSB."""
        result = ha_notify.recommend_workout(
            acwr=1.0, tsb=-3, body_battery=65, stress_score=40,
            sleep_debt_minutes=0, consecutive_hard_days=0,
            readiness_score=75,
        )
        assert result["workout_type"] == "quality"


class TestAerobicSession:
    """Test conditions for moderate/aerobic recommendations."""

    def test_moderate_readiness_aerobic(self, ha_notify):
        """Moderate readiness (50-70) should recommend aerobic work."""
        result = ha_notify.recommend_workout(
            acwr=1.0, tsb=-8, body_battery=55, stress_score=45,
            sleep_debt_minutes=60, consecutive_hard_days=1,
            readiness_score=55,
        )
        assert result["workout_type"] == "aerobic"
        assert result["intensity"] == "moderate"
        assert result["hr_zone_target"] == 2


class TestDefaultEasyDay:
    """Test the fallback easy day recommendation."""

    def test_all_none_gives_easy(self, ha_notify):
        """When all inputs are None, defaults give aerobic (readiness=50, BB=50)."""
        result = ha_notify.recommend_workout(
            acwr=None, tsb=None, body_battery=None, stress_score=None,
            sleep_debt_minutes=None, consecutive_hard_days=0,
            readiness_score=None,
        )
        assert result["is_rest_day"] is False
        assert result["workout_type"] in ("easy", "aerobic")

    def test_low_body_battery_neutral_else(self, ha_notify):
        """Low BB but not critical + neutral everything = easy day."""
        result = ha_notify.recommend_workout(
            acwr=1.0, tsb=-12, body_battery=40, stress_score=50,
            sleep_debt_minutes=30, consecutive_hard_days=0,
            readiness_score=45,
        )
        assert result["workout_type"] in ("easy", "aerobic")


class TestReadinessZone:
    """Test readiness zone classification."""

    def test_zones(self, ha_notify):
        """Verify readiness zone helper if exposed via metrics-compute."""
        # This tests the recommend_workout response includes zone context
        result = ha_notify.recommend_workout(
            acwr=1.0, tsb=15, body_battery=90, stress_score=20,
            sleep_debt_minutes=0, consecutive_hard_days=0,
            readiness_score=90,
        )
        assert result["workout_type"] == "quality"
        assert "Readiness 90" in result["rationale"]
