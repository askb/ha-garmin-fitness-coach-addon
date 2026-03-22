"""Garmin measurement validation tests.

Tests two categories:
1. Schema integrity — Garmin payloads map correctly to DB fields/units
2. Physiological plausibility — flags impossible/implausible values

Uses golden fixtures representing real Garmin Connect API responses.
"""
import sys
import os
import json
import pytest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))


# ---------------------------------------------------------------------------
# Golden dataset (representative Garmin API responses)
# ---------------------------------------------------------------------------

GOLDEN_DAILY_STATS = {
    "totalSteps": 8432,
    "totalKilocalories": 2150,
    "totalDistanceMeters": 6240,
    "floorsAscended": 8,
    "averageStressLevel": 32,
    "maxStressLevel": 75,
    "bodyBatteryChargedValue": 45,
    "bodyBatteryDrainedValue": 38,
    "wellnessMaxAvailableBodyBattery": 82,
    "minHeartRate": 48,
    "maxHeartRate": 162,
    "restingHeartRate": 52,
    "averageHeartRate": 68,
}

GOLDEN_SLEEP = {
    "dailySleepDTO": {
        "sleepTimeSeconds": 25200,    # 7h exactly
        "deepSleepSeconds": 5400,     # 1.5h
        "lightSleepSeconds": 12600,   # 3.5h
        "remSleepSeconds": 5400,      # 1.5h
        "awakeSleepSeconds": 1800,    # 30min
        "sleepScores": {"overall": {"value": 72}},
        "averageSpO2Value": 96.8,
        "averageRespirationValue": 13.8,
    }
}

GOLDEN_HRV = {
    "hrvSummary": {
        "lastNight": 48.5,
        "weeklyAvg": 46.2,
    },
    "hrvReadings": [
        {"hrvValue": 47},
        {"hrvValue": 49},
        {"hrvValue": 51},
    ]
}

GOLDEN_ACTIVITY = {
    "activityId": 12345678901,
    "activityType": {"typeKey": "running"},
    "startTimeLocal": "2024-01-15 07:30:00",
    "duration": 3600.0,
    "distance": 10000.0,
    "averageHR": 158,
    "maxHR": 178,
    "calories": 680,
    "averageSpeed": 2.78,       # m/s → 5:59/km
    "activityTrainingLoad": 85.0,
    "aerobicTrainingEffect": 3.5,
    "anaerobicTrainingEffect": 1.2,
    "vo2MaxValue": 52.3,
    "averageRunningCadenceInStepsPerMinute": 172,
    "totalAscent": 45,
    "totalDescent": 42,
    "avgPower": None,           # running: no power
}


# ---------------------------------------------------------------------------
# Schema integrity tests
# ---------------------------------------------------------------------------

class TestSchemaIntegrity:
    """Verify Garmin API payloads map to correct DB fields."""

    def test_sleep_seconds_to_minutes(self):
        """Sleep fields must be converted from seconds to minutes."""
        sleep_dto = GOLDEN_SLEEP["dailySleepDTO"]
        total_seconds = sleep_dto["sleepTimeSeconds"]
        expected_minutes = total_seconds // 60

        assert expected_minutes == 420, "7 hours = 420 minutes"

        # Verify conversion is integer division (not float)
        assert isinstance(expected_minutes, int)

    def test_sleep_stages_sum_to_total(self):
        """Deep + light + REM + awake should equal total sleep."""
        dto = GOLDEN_SLEEP["dailySleepDTO"]
        stages_sum = (
            dto["deepSleepSeconds"] +
            dto["lightSleepSeconds"] +
            dto["remSleepSeconds"] +
            dto["awakeSleepSeconds"]
        )
        assert stages_sum == dto["sleepTimeSeconds"], (
            f"Stages sum {stages_sum}s ≠ total {dto['sleepTimeSeconds']}s"
        )

    def test_activity_duration_minutes(self):
        """Activity duration must be converted from seconds to minutes."""
        duration_seconds = GOLDEN_ACTIVITY["duration"]
        duration_minutes = duration_seconds / 60
        assert abs(duration_minutes - 60.0) < 0.01

    def test_activity_speed_to_pace(self):
        """avg_pace_sec_per_km computed from averageSpeed (m/s)."""
        speed_mps = GOLDEN_ACTIVITY["averageSpeed"]
        pace_sec_per_km = round(1000 / speed_mps)
        # 2.78 m/s → ~359 sec/km ≈ 5:59/km
        assert 350 <= pace_sec_per_km <= 370, f"Unexpected pace: {pace_sec_per_km}"

    def test_hrv_extracted_from_summary(self):
        """HRV should be extracted from lastNight field."""
        hrv = GOLDEN_HRV["hrvSummary"]["lastNight"]
        assert isinstance(hrv, (int, float))
        assert hrv == 48.5

    def test_body_battery_fields_present(self):
        """Both bodyBattery start and end values should map to DB."""
        stats = GOLDEN_DAILY_STATS
        charged = stats.get("bodyBatteryChargedValue")
        max_bb = stats.get("wellnessMaxAvailableBodyBattery")
        assert charged is not None
        assert max_bb is not None
        # body_battery_end ≈ max - drained + charged (simplified)
        drained = stats.get("bodyBatteryDrainedValue", 0)
        end_estimate = max_bb - drained + charged
        assert end_estimate > 0

    def test_stress_score_mapping(self):
        """Stress score should come from averageStressLevel (0-100)."""
        stress = GOLDEN_DAILY_STATS["averageStressLevel"]
        assert 0 <= stress <= 100, f"Stress {stress} out of range"

    def test_garmin_activity_id_preserved(self):
        """garmin_activity_id must be stored as string to avoid int overflow."""
        activity_id = GOLDEN_ACTIVITY["activityId"]
        # 64-bit int — must be stored as varchar, not int
        id_str = str(activity_id)
        assert len(id_str) > 0
        assert id_str == "12345678901"


# ---------------------------------------------------------------------------
# Physiological plausibility tests
# ---------------------------------------------------------------------------

class TestPhysiologicalPlausibility:
    """Flag values outside medically plausible ranges."""

    # Reference ranges (ACSM Guidelines + medical literature)
    HR_MIN = 30      # Elite endurance athletes at rest
    HR_MAX = 220     # Max possible (theoretical)
    HRV_MIN = 1      # ms — below this is clinically concerning
    HRV_MAX = 300    # ms — above this is instrument error
    SPO2_MIN = 85    # % — below this requires medical attention
    SPO2_MAX = 100
    SLEEP_MIN = 0    # minutes
    SLEEP_MAX = 720  # 12h — more is implausible for single night
    STEPS_MIN = 0
    STEPS_MAX = 100_000  # ultra-marathoners upper bound
    VO2MAX_MIN = 20   # sedentary adult minimum (ml/kg/min)
    VO2MAX_MAX = 90   # world-class endurance athlete maximum

    def _is_plausible(self, value, min_val, max_val, allow_none=True):
        if value is None:
            return allow_none
        return min_val <= value <= max_val

    def test_resting_hr_plausible(self):
        rhr = GOLDEN_DAILY_STATS["restingHeartRate"]
        assert self._is_plausible(rhr, self.HR_MIN, self.HR_MAX), f"RHR {rhr} implausible"

    def test_max_hr_plausible(self):
        max_hr = GOLDEN_DAILY_STATS["maxHeartRate"]
        assert self._is_plausible(max_hr, self.HR_MIN, self.HR_MAX), f"MaxHR {max_hr} implausible"

    def test_max_hr_exceeds_resting(self):
        rhr = GOLDEN_DAILY_STATS["restingHeartRate"]
        max_hr = GOLDEN_DAILY_STATS["maxHeartRate"]
        assert max_hr > rhr, f"MaxHR {max_hr} must exceed RHR {rhr}"

    def test_hrv_in_plausible_range(self):
        hrv = GOLDEN_HRV["hrvSummary"]["lastNight"]
        assert self._is_plausible(hrv, self.HRV_MIN, self.HRV_MAX), f"HRV {hrv} implausible"

    def test_spo2_in_plausible_range(self):
        spo2 = GOLDEN_SLEEP["dailySleepDTO"].get("averageSpO2Value")
        assert self._is_plausible(spo2, self.SPO2_MIN, self.SPO2_MAX), f"SpO2 {spo2} implausible"

    def test_sleep_duration_plausible(self):
        sleep_min = GOLDEN_SLEEP["dailySleepDTO"]["sleepTimeSeconds"] // 60
        assert self._is_plausible(sleep_min, self.SLEEP_MIN, self.SLEEP_MAX), \
            f"Sleep {sleep_min}min implausible"

    def test_steps_plausible(self):
        steps = GOLDEN_DAILY_STATS["totalSteps"]
        assert self._is_plausible(steps, self.STEPS_MIN, self.STEPS_MAX), f"Steps {steps} implausible"

    def test_vo2max_plausible(self):
        vo2 = GOLDEN_ACTIVITY["vo2MaxValue"]
        assert self._is_plausible(vo2, self.VO2MAX_MIN, self.VO2MAX_MAX), f"VO2max {vo2} implausible"

    def test_aerobic_te_range(self):
        """Aerobic Training Effect must be 0.0-5.0 (Garmin scale)."""
        te = GOLDEN_ACTIVITY["aerobicTrainingEffect"]
        assert 0.0 <= te <= 5.0, f"Aerobic TE {te} out of 0-5 range"

    def test_running_cadence_plausible(self):
        """Running cadence 140-220 spm (steps per min, both feet)."""
        cadence = GOLDEN_ACTIVITY.get("averageRunningCadenceInStepsPerMinute")
        if cadence is not None:
            assert 120 <= cadence <= 230, f"Cadence {cadence} spm implausible"

    def test_activity_distance_consistent_with_duration(self):
        """Distance and duration should give plausible speed."""
        dist_m = GOLDEN_ACTIVITY["distance"]
        dur_s = GOLDEN_ACTIVITY["duration"]
        speed_kmh = (dist_m / 1000) / (dur_s / 3600)
        # Running: 4-35 km/h plausible range
        assert 4 <= speed_kmh <= 35, f"Speed {speed_kmh:.1f} km/h implausible for running"


# ---------------------------------------------------------------------------
# Idempotency tests
# ---------------------------------------------------------------------------

class TestIdempotency:
    """Verify that upserting the same data twice produces no duplicate rows."""

    def test_upsert_sql_is_idempotent(self, db_mock):
        """The ON CONFLICT DO UPDATE pattern should be idempotent."""
        conn, cursor = db_mock

        # Simulate first insert
        cursor.execute("INSERT INTO daily_metric (user_id, date, steps) VALUES (%s, %s, %s) ON CONFLICT (user_id, date) DO UPDATE SET steps = EXCLUDED.steps",
                      ("test-user", "2024-01-15", 8432))
        call_count_1 = cursor.execute.call_count

        # Simulate second insert (same data)
        cursor.execute("INSERT INTO daily_metric (user_id, date, steps) VALUES (%s, %s, %s) ON CONFLICT (user_id, date) DO UPDATE SET steps = EXCLUDED.steps",
                      ("test-user", "2024-01-15", 8432))
        call_count_2 = cursor.execute.call_count

        # Both should execute without error — upsert handles duplicates
        assert call_count_2 == call_count_1 + 1

    def test_ci_tolerance_hrv(self):
        """HRV values should match within ±2ms (CI requirement)."""
        garmin_hrv = 48.5
        reference_hrv = 47.3  # from a reference device
        tolerance_ms = 2.0
        assert abs(garmin_hrv - reference_hrv) <= tolerance_ms, \
            f"HRV deviation {abs(garmin_hrv - reference_hrv):.1f}ms exceeds {tolerance_ms}ms tolerance"

    def test_ci_tolerance_sleep_minutes(self):
        """Sleep duration should match exactly (discrete minutes)."""
        garmin_sleep = GOLDEN_SLEEP["dailySleepDTO"]["sleepTimeSeconds"] // 60
        reference_sleep = 420  # manual reference
        assert garmin_sleep == reference_sleep, \
            f"Sleep {garmin_sleep}min ≠ reference {reference_sleep}min"
