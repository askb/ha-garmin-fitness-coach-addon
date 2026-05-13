# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Tests for ha-notify.py sensor helpers introduced in Phase 3.

Covers the pure helpers that feed the new HA sensors:
  - ``_compute_hrv_trend`` — 7-day HRV trend label + average
  - ``_derive_load_focus_label`` — load-focus heuristic over Garmin's JSONB

Both helpers were extracted from inline code so they can be unit-tested
without standing up a database or HA Supervisor.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "pulsecoach" / "rootfs" / "app" / "scripts"


def _load_ha_notify() -> types.ModuleType:
    mock_psycopg2 = MagicMock()
    mock_psycopg2.extras = MagicMock()
    with patch.dict(sys.modules, {
        "psycopg2": mock_psycopg2,
        "psycopg2.extras": mock_psycopg2.extras,
    }):
        spec = importlib.util.spec_from_file_location("ha_notify", SCRIPTS_DIR / "ha-notify.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ha_notify():
    return _load_ha_notify()


# ── HRV trend ────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestComputeHrvTrend:
    """Pure-function tests for ``_compute_hrv_trend``."""

    def test_returns_none_for_empty_input(self, ha_notify):
        assert ha_notify._compute_hrv_trend([]) == (None, None)
        assert ha_notify._compute_hrv_trend(None) == (None, None)

    def test_requires_at_least_three_rows(self, ha_notify):
        """Fewer than 3 datapoints → no trend (insufficient signal)."""
        rows = [{"hrv": 50}, {"hrv": 52}]
        assert ha_notify._compute_hrv_trend(rows) == (None, None)

    def test_rising_when_latest_above_5pct_band(self, ha_notify):
        rows = [{"hrv": 50}, {"hrv": 50}, {"hrv": 60}]
        # avg = (50+50+60)/3 ≈ 53.3; latest 60 > 53.3*1.05 (≈56.0) → rising
        trend, avg = ha_notify._compute_hrv_trend(rows)
        assert trend == "rising"
        assert avg == pytest.approx(53.3, abs=0.1)

    def test_falling_when_latest_below_5pct_band(self, ha_notify):
        rows = [{"hrv": 60}, {"hrv": 60}, {"hrv": 50}]
        trend, _ = ha_notify._compute_hrv_trend(rows)
        assert trend == "falling"

    def test_stable_within_band(self, ha_notify):
        rows = [{"hrv": 50}, {"hrv": 51}, {"hrv": 50}]
        trend, avg = ha_notify._compute_hrv_trend(rows)
        assert trend == "stable"
        assert avg == pytest.approx(50.3, abs=0.1)

    def test_accepts_string_hrv_values(self, ha_notify):
        """psycopg2 sometimes returns Decimal/str — helper coerces to float."""
        rows = [{"hrv": "50"}, {"hrv": "50"}, {"hrv": "60"}]
        trend, _ = ha_notify._compute_hrv_trend(rows)
        assert trend == "rising"


# ── Load focus heuristic ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestDeriveLoadFocusLabel:
    """Pure-function tests for ``_derive_load_focus_label``."""

    def test_unknown_for_none(self, ha_notify):
        assert ha_notify._derive_load_focus_label(None) == "unknown"

    def test_unknown_for_empty_dict(self, ha_notify):
        assert ha_notify._derive_load_focus_label({}) == "unknown"

    def test_unknown_for_non_dict_non_string(self, ha_notify):
        assert ha_notify._derive_load_focus_label(42) == "unknown"
        assert ha_notify._derive_load_focus_label([1, 2]) == "unknown"

    def test_string_payload_lowercased(self, ha_notify):
        assert ha_notify._derive_load_focus_label("HIGH_AEROBIC") == "high_aerobic"

    def test_anaerobic_dominates_via_percentages(self, ha_notify):
        payload = {
            "lowAerobicTrainingLoadPercentage": 10,
            "highAerobicTrainingLoadPercentage": 20,
            "anaerobicTrainingLoadPercentage": 70,
        }
        assert ha_notify._derive_load_focus_label(payload) == "anaerobic"

    def test_high_aerobic_dominates_via_percentages(self, ha_notify):
        payload = {
            "lowAerobicTrainingLoadPercentage": 20,
            "highAerobicTrainingLoadPercentage": 60,
            "anaerobicTrainingLoadPercentage": 20,
        }
        assert ha_notify._derive_load_focus_label(payload) == "high_aerobic"

    def test_low_aerobic_dominates_via_percentages(self, ha_notify):
        payload = {
            "lowAerobicTrainingLoadPercentage": 70,
            "highAerobicTrainingLoadPercentage": 20,
            "anaerobicTrainingLoadPercentage": 10,
        }
        assert ha_notify._derive_load_focus_label(payload) == "low_aerobic"

    def test_falls_back_to_absolute_keys(self, ha_notify):
        """When only absolute keys are present, the heuristic still works."""
        payload = {
            "lowAerobicTrainingLoad": 100,
            "highAerobicTrainingLoad": 50,
            "anaerobicTrainingLoad": 200,
        }
        assert ha_notify._derive_load_focus_label(payload) == "anaerobic"

    def test_prefers_percentages_when_both_present(self, ha_notify):
        """If both pct and abs keys exist, percentage values win."""
        payload = {
            # Percentages say anaerobic dominates
            "lowAerobicTrainingLoadPercentage": 10,
            "highAerobicTrainingLoadPercentage": 20,
            "anaerobicTrainingLoadPercentage": 70,
            # Absolute values would say low_aerobic — should be ignored
            "lowAerobicTrainingLoad": 500,
            "highAerobicTrainingLoad": 100,
            "anaerobicTrainingLoad": 50,
        }
        assert ha_notify._derive_load_focus_label(payload) == "anaerobic"

    def test_unknown_when_all_zero(self, ha_notify):
        payload = {
            "lowAerobicTrainingLoadPercentage": 0,
            "highAerobicTrainingLoadPercentage": 0,
            "anaerobicTrainingLoadPercentage": 0,
        }
        assert ha_notify._derive_load_focus_label(payload) == "unknown"
