# SPDX-FileCopyrightText: 2025 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Pytest unit tests for garmin-sync.py.

Coverage:
- _safe_sleep_minutes()      — edge cases (None, 0, missing key, negative)
- sync_daily_stats()         — mock Garmin API responses, verify DB inserts
- sync_activities()          — activity parsing, HR zone extraction, TRIMP
- sync_vo2max()              — Garmin max-metrics API parsing, Uth fallback
- backfill_from_raw_json()   — strain/zone extraction from raw data

Run with:
    pytest tests/ -v
"""

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "pulsecoach"
    / "rootfs"
    / "app"
    / "scripts"
    / "garmin-sync.py"
)


@pytest.fixture()
def garmin_sync():
    """Import garmin-sync.py with garminconnect mocked (psycopg2 is installed)."""
    mock_garminconnect = MagicMock()
    with patch.dict(sys.modules, {"garminconnect": mock_garminconnect}):
        spec = importlib.util.spec_from_file_location("garmin_sync", SCRIPT_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        yield mod


@pytest.fixture()
def mock_db():
    """Return a (connection, cursor) pair backed by MagicMock (no real DB needed)."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


@pytest.fixture()
def mock_client():
    """Return a mock Garmin client with realistic return values."""
    client = MagicMock()
    client.get_stats.return_value = {
        "totalSteps": 8500,
        "totalKilocalories": 2100,
        "restingHeartRate": 58,
        "maxHeartRate": 145,
        "bodyBatteryChargedValue": 80,
        "bodyBatteryDrainedValue": 55,
        "floorsAscended": 12,
        "intensityMinutesGoal": 150,
    }
    client.get_sleep_data.return_value = {
        "dailySleepDTO": {
            "sleepTimeSeconds": 28800,   # 480 min
            "deepSleepSeconds": 7200,    # 120 min
            "remSleepSeconds": 5400,     # 90 min
            "lightSleepSeconds": 14400,  # 240 min
            "awakeSleepSeconds": 1800,   # 30 min
            "sleepScores": {"overall": {"value": 82}},
        }
    }
    client.get_hrv_data.return_value = {"hrvSummary": {"weeklyAvg": 42}}
    client.get_stress_data.return_value = {"avgStressLevel": 35}
    client.get_activities.return_value = [
        {
            "activityId": 99001,
            "activityType": {"typeKey": "running", "typeId": "1"},
            "startTimeLocal": "2025-01-15 07:30:00",
            "duration": 1800.0,   # 30 min
            "distance": 5000.0,
            "averageHR": 150,
            "maxHR": 175,
            "calories": 400,
            "averageSpeed": 2.78,
            "aerobicTrainingEffect": 3.5,
            "anaerobicTrainingEffect": 1.2,
            "hrTimeInZone_1": 180,   # 3 min
            "hrTimeInZone_2": 300,   # 5 min
            "hrTimeInZone_3": 600,   # 10 min
            "hrTimeInZone_4": 420,   # 7 min
            "hrTimeInZone_5": 300,   # 5 min
        },
    ]
    return client


# ---------------------------------------------------------------------------
# _safe_sleep_minutes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSafeSleepMinutes:
    """Edge-case tests for _safe_sleep_minutes()."""

    def test_converts_seconds_to_minutes(self, garmin_sync):
        """Positive seconds are correctly divided by 60 (integer division)."""
        result = garmin_sync._safe_sleep_minutes(
            {"sleepTimeSeconds": 28800}, "sleepTimeSeconds"
        )
        assert result == 480

    def test_none_value_returns_none(self, garmin_sync):
        """When the stored value is None the function returns None."""
        result = garmin_sync._safe_sleep_minutes(
            {"sleepTimeSeconds": None}, "sleepTimeSeconds"
        )
        assert result is None

    def test_missing_key_returns_none(self, garmin_sync):
        """When the key is absent the function returns None."""
        result = garmin_sync._safe_sleep_minutes({}, "sleepTimeSeconds")
        assert result is None

    def test_zero_seconds_returns_zero(self, garmin_sync):
        """Zero seconds converts to zero minutes."""
        result = garmin_sync._safe_sleep_minutes(
            {"sleepTimeSeconds": 0}, "sleepTimeSeconds"
        )
        assert result == 0

    def test_negative_seconds_returns_negative_minutes(self, garmin_sync):
        """Negative input is handled without raising (returns negative minutes).

        Negative sleep durations should not occur in production, but the helper
        uses integer-division and does not clamp the result.  This test confirms
        the current behaviour (no crash) rather than endorsing it as valid data.
        """
        result = garmin_sync._safe_sleep_minutes(
            {"sleepTimeSeconds": -3600}, "sleepTimeSeconds"
        )
        assert result == -60


# ---------------------------------------------------------------------------
# sync_daily_stats
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSyncDailyStats:
    """Tests for sync_daily_stats() — mock Garmin API, verify DB cursor calls."""

    def _get_insert_values(self, cursor):
        """Return the VALUES tuple from the INSERT INTO daily_metric execute call."""
        insert_call = next(
            (c for c in cursor.execute.call_args_list
             if "INSERT INTO daily_metric" in c[0][0]),
            None,
        )
        assert insert_call is not None, "No INSERT INTO daily_metric call found"
        return insert_call[0][1]

    def test_calls_db_insert_and_commit(self, garmin_sync, mock_db, mock_client):
        """sync_daily_stats() executes an INSERT and commits the transaction."""
        conn, cursor = mock_db
        garmin_sync.sync_daily_stats(mock_client, conn, "2025-01-15")
        assert cursor.execute.called
        conn.commit.assert_called_once()

    def test_passes_steps_to_db(self, garmin_sync, mock_db, mock_client):
        """The totalSteps value from the API is included in the INSERT values."""
        conn, cursor = mock_db
        garmin_sync.sync_daily_stats(mock_client, conn, "2025-01-15")
        values = self._get_insert_values(cursor)
        assert 8500 in values

    def test_converts_sleep_seconds_to_minutes(self, garmin_sync, mock_db, mock_client):
        """Sleep fields are converted from seconds to minutes in the INSERT values."""
        conn, cursor = mock_db
        garmin_sync.sync_daily_stats(mock_client, conn, "2025-01-15")
        values = self._get_insert_values(cursor)
        assert 480 in values  # total: 28800 s → 480 min
        assert 120 in values  # deep:  7200 s → 120 min
        assert 90 in values   # rem:   5400 s → 90 min
        assert 240 in values  # light: 14400 s → 240 min
        assert 30 in values   # awake: 1800 s → 30 min

    def test_passes_date_string_to_db(self, garmin_sync, mock_db, mock_client):
        """The date string supplied to the function is stored in the INSERT values."""
        conn, cursor = mock_db
        garmin_sync.sync_daily_stats(mock_client, conn, "2025-01-15")
        values = self._get_insert_values(cursor)
        assert "2025-01-15" in values

    def test_handles_api_error_gracefully(
        self, garmin_sync, mock_db, mock_client, capsys
    ):
        """An API error is caught, rolled back, and printed to stderr."""
        conn, cursor = mock_db
        mock_client.get_stats.side_effect = ConnectionError("timeout")
        garmin_sync.sync_daily_stats(mock_client, conn, "2025-01-15")
        conn.rollback.assert_called_once()
        assert "Failed to sync" in capsys.readouterr().err

    def test_handles_none_sleep_data_gracefully(
        self, garmin_sync, mock_db, mock_client
    ):
        """None sleep data is handled without raising — commit still occurs."""
        conn, cursor = mock_db
        mock_client.get_sleep_data.return_value = None
        garmin_sync.sync_daily_stats(mock_client, conn, "2025-01-15")
        conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# sync_activities
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSyncActivities:
    """Tests for sync_activities() — activity parsing, HR zones, TRIMP."""

    def _get_activity_insert_call(self, cursor):
        """Return the execute call for INSERT INTO activity."""
        return next(
            (c for c in cursor.execute.call_args_list
             if "INSERT INTO activity" in c[0][0]),
            None,
        )

    def test_inserts_one_activity_per_api_record(
        self, garmin_sync, mock_db, mock_client
    ):
        """Each activity from the API results in one INSERT INTO activity call."""
        conn, cursor = mock_db
        garmin_sync.sync_activities(mock_client, conn, days=7)
        insert_calls = [
            c for c in cursor.execute.call_args_list
            if "INSERT INTO activity" in c[0][0]
        ]
        assert len(insert_calls) == 1

    def test_stores_raw_garmin_json(self, garmin_sync, mock_db, mock_client):
        """The raw Garmin activity dict is serialised to JSON in the INSERT values."""
        conn, cursor = mock_db
        garmin_sync.sync_activities(mock_client, conn, days=7)
        insert_call = self._get_activity_insert_call(cursor)
        assert insert_call is not None
        # raw_garmin_data is the last positional argument
        raw = json.loads(insert_call[0][1][-1])
        assert raw["activityId"] == 99001

    def test_extracts_hr_zone_minutes(self, garmin_sync, mock_db, mock_client):
        """HR zone seconds are converted to minutes and stored as a JSON string."""
        conn, cursor = mock_db
        garmin_sync.sync_activities(mock_client, conn, days=7)
        insert_call = self._get_activity_insert_call(cursor)
        assert insert_call is not None
        values = insert_call[0][1]
        # Locate the hr_zone_minutes JSON among the values
        hr_zones_json = next(
            (v for v in values if isinstance(v, str) and "zone1" in v), None
        )
        assert hr_zones_json is not None
        hr_zones = json.loads(hr_zones_json)
        assert hr_zones["zone1"] == 3.0    # 180 s / 60
        assert hr_zones["zone2"] == 5.0    # 300 s / 60
        assert hr_zones["zone3"] == 10.0   # 600 s / 60
        assert hr_zones["zone4"] == 7.0    # 420 s / 60
        assert hr_zones["zone5"] == 5.0    # 300 s / 60

    def test_calculates_trimp_score(self, garmin_sync, mock_db, mock_client):
        """TRIMP is computed from avg HR and duration and included in the INSERT.

        Formula: duration_min * hr_ratio * 0.64 * (1.92 ** hr_ratio)
        where hr_ratio = avg_hr / 200.0  (200 bpm = normalization constant).
        """
        conn, cursor = mock_db
        garmin_sync.sync_activities(mock_client, conn, days=7)
        insert_call = self._get_activity_insert_call(cursor)
        assert insert_call is not None
        values = insert_call[0][1]
        # Expected: duration_min=30, hr_ratio=150/200.0=0.75
        HR_NORM = 200.0  # normalization constant used in the TRIMP formula
        hr_ratio = 150 / HR_NORM
        expected_trimp = round(30 * hr_ratio * 0.64 * (1.92 ** hr_ratio), 1)
        assert expected_trimp in values

    def test_handles_api_error_gracefully(
        self, garmin_sync, mock_db, mock_client, capsys
    ):
        """An API error is caught, rolled back, and printed to stderr."""
        conn, cursor = mock_db
        mock_client.get_activities.side_effect = ConnectionError("network down")
        garmin_sync.sync_activities(mock_client, conn, days=7)
        conn.rollback.assert_called_once()
        assert "Failed to sync activities" in capsys.readouterr().err

    def test_stops_batching_when_api_returns_empty(
        self, garmin_sync, mock_db, mock_client
    ):
        """The batch loop stops when the API returns an empty list."""
        conn, cursor = mock_db
        mock_client.get_activities.side_effect = [
            mock_client.get_activities.return_value,  # first batch: 1 activity
            [],                                        # second batch: empty → stop
        ]
        garmin_sync.sync_activities(mock_client, conn, days=7)
        # Only the first batch should produce an INSERT
        insert_calls = [
            c for c in cursor.execute.call_args_list
            if "INSERT INTO activity" in c[0][0]
        ]
        assert len(insert_calls) == 1


# ---------------------------------------------------------------------------
# sync_vo2max
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSyncVo2max:
    """Tests for sync_vo2max() — official Garmin API and Uth fallback."""

    def test_official_api_inserts_vo2max_record(
        self, garmin_sync, mock_db, mock_client
    ):
        """A valid VO2max from get_max_metrics is inserted into vo2max_estimate."""
        conn, cursor = mock_db
        mock_client.get_max_metrics.return_value = [
            {
                "generic": {"vo2MaxPreciseValue": 52.3},
                "calendarDate": "2025-01-15",
            }
        ]
        garmin_sync.sync_vo2max(mock_client, conn, days=1)
        insert_calls = [
            c for c in cursor.execute.call_args_list
            if "INSERT INTO vo2max_estimate" in c[0][0]
        ]
        assert len(insert_calls) >= 1

    def test_official_api_stores_correct_value(
        self, garmin_sync, mock_db, mock_client
    ):
        """The VO2max value from the API is rounded to one decimal place."""
        conn, cursor = mock_db
        mock_client.get_max_metrics.return_value = [
            {
                "generic": {"vo2MaxPreciseValue": 52.349},
                "calendarDate": "2025-01-15",
            }
        ]
        garmin_sync.sync_vo2max(mock_client, conn, days=1)
        insert_call = next(
            (c for c in cursor.execute.call_args_list
             if "INSERT INTO vo2max_estimate" in c[0][0]),
            None,
        )
        assert insert_call is not None
        values = insert_call[0][1]
        assert 52.3 in values

    def test_cycling_vo2max_detected(self, garmin_sync, mock_db, mock_client):
        """A cycling VO2max entry sets sport='cycling'."""
        conn, cursor = mock_db
        mock_client.get_max_metrics.return_value = [
            {
                "generic": {},
                "cycling": {"vo2MaxPreciseValue": 55.0},
                "calendarDate": "2025-01-15",
            }
        ]
        garmin_sync.sync_vo2max(mock_client, conn, days=1)
        insert_call = next(
            (c for c in cursor.execute.call_args_list
             if "INSERT INTO vo2max_estimate" in c[0][0]),
            None,
        )
        assert insert_call is not None
        values = insert_call[0][1]
        assert "cycling" in values

    def test_uth_fallback_when_official_api_empty(
        self, garmin_sync, mock_db, mock_client
    ):
        """Uth method is used when the official Garmin API returns no usable data."""
        conn, cursor = mock_db
        # No VO2max from official API
        mock_client.get_max_metrics.return_value = []
        # Profile age = 35 (used to compute age-predicted HRmax = 220 - 35 = 185)
        cursor.fetchone.return_value = {'age': 35}
        # Provide one resting-HR row (resting_hr=58)
        cursor.fetchmany.side_effect = [
            [{'date': '2025-01-15', 'resting_hr': 58}],  # first fetchmany batch
            [],                     # second call → stop loop
        ]
        garmin_sync.sync_vo2max(mock_client, conn, days=1)
        uth_inserts = [
            c for c in cursor.execute.call_args_list
            if "INSERT INTO vo2max_estimate" in c[0][0]
            and "uth_method" in str(c)
        ]
        assert len(uth_inserts) >= 1

    def test_uth_fallback_computes_correct_vo2max(
        self, garmin_sync, mock_db, mock_client
    ):
        """Uth VO2max = 15.3 * (HRmax / resting_hr) rounded to 1 dp."""
        conn, cursor = mock_db
        mock_client.get_max_metrics.return_value = []
        # age=35 fetched from the profile table → HRmax = 220 - 35 = 185
        cursor.fetchone.return_value = {'age': 35}
        cursor.fetchmany.side_effect = [
            [{'date': '2025-01-15', 'resting_hr': 58}],
            [],
        ]
        garmin_sync.sync_vo2max(mock_client, conn, days=1)
        expected_vo2 = round(15.3 * (185 / 58), 1)
        uth_insert = next(
            (c for c in cursor.execute.call_args_list
             if "INSERT INTO vo2max_estimate" in c[0][0]
             and "uth_method" in str(c)),
            None,
        )
        assert uth_insert is not None
        assert expected_vo2 in uth_insert[0][1]

    def test_skips_unrealistic_vo2max_values(
        self, garmin_sync, mock_db, mock_client
    ):
        """VO2max values outside [10, 90] are silently discarded."""
        conn, cursor = mock_db
        mock_client.get_max_metrics.return_value = [
            {"generic": {"vo2MaxPreciseValue": 5.0}, "calendarDate": "2025-01-15"},
        ]
        # Prevent the Uth fallback's while-loop from running indefinitely
        cursor.fetchmany.return_value = []
        garmin_sync.sync_vo2max(mock_client, conn, days=1)
        insert_calls = [
            c for c in cursor.execute.call_args_list
            if "INSERT INTO vo2max_estimate" in c[0][0]
        ]
        assert len(insert_calls) == 0


# ---------------------------------------------------------------------------
# backfill_from_raw_json
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBackfillFromRawJson:
    """Tests for backfill_from_raw_json() — strain/zone extraction from raw data."""

    def _raw_activity(self, **extra):
        base = {
            "activityId": 77001,
            "activityTrainingLoad": 85.0,
        }
        base.update(extra)
        return json.dumps(base)

    def test_skips_when_no_rows_need_backfill(self, garmin_sync, mock_db):
        """When there are no qualifying rows, no UPDATE is executed."""
        conn, cursor = mock_db
        cursor.fetchall.return_value = []
        garmin_sync.backfill_from_raw_json(conn)
        update_calls = [
            c for c in cursor.execute.call_args_list
            if "UPDATE activity" in c[0][0]
        ]
        assert len(update_calls) == 0

    def test_extracts_hr_zone_minutes_from_raw_data(self, garmin_sync, mock_db):
        """HR zone seconds in raw JSON are converted to minutes and stored."""
        conn, cursor = mock_db
        raw = self._raw_activity(
            hrTimeInZone_1=180,
            hrTimeInZone_2=300,
            hrTimeInZone_3=600,
            hrTimeInZone_4=420,
            hrTimeInZone_5=300,
        )
        cursor.fetchall.return_value = [{'id': 1, 'raw_garmin_data': raw, 'avg_hr': 150, 'duration_minutes': 30.0}]
        garmin_sync.backfill_from_raw_json(conn)
        update_calls = [
            c for c in cursor.execute.call_args_list
            if "UPDATE activity" in c[0][0]
        ]
        assert len(update_calls) == 1
        values = update_calls[0][0][1]
        hr_zones_json = next(
            (v for v in values if isinstance(v, str) and "zone1" in v), None
        )
        assert hr_zones_json is not None
        hr_zones = json.loads(hr_zones_json)
        assert hr_zones["zone1"] == 3.0
        assert hr_zones["zone3"] == 10.0

    def test_computes_trimp_from_avg_hr_and_duration(self, garmin_sync, mock_db):
        """TRIMP is recomputed from avg_hr and duration_minutes stored in the DB row."""
        conn, cursor = mock_db
        raw = self._raw_activity()
        # avg_hr=150, duration_min=30
        cursor.fetchall.return_value = [{'id': 1, 'raw_garmin_data': raw, 'avg_hr': 150, 'duration_minutes': 30.0}]
        garmin_sync.backfill_from_raw_json(conn)
        update_calls = [
            c for c in cursor.execute.call_args_list
            if "UPDATE activity" in c[0][0]
        ]
        assert len(update_calls) == 1
        values = update_calls[0][0][1]
        # trimp_score is the third parameter (index 2)
        trimp = values[2]
        hr_ratio = 150 / 200.0
        expected = round(30 * hr_ratio * 0.64 * (1.92 ** hr_ratio), 1)
        assert trimp == expected

    def test_stores_strain_score_from_raw_data(self, garmin_sync, mock_db):
        """activityTrainingLoad in raw JSON is stored as strain_score."""
        conn, cursor = mock_db
        raw = self._raw_activity(activityTrainingLoad=92.5)
        cursor.fetchall.return_value = [{'id': 1, 'raw_garmin_data': raw, 'avg_hr': 150, 'duration_minutes': 30.0}]
        garmin_sync.backfill_from_raw_json(conn)
        update_calls = [
            c for c in cursor.execute.call_args_list
            if "UPDATE activity" in c[0][0]
        ]
        assert len(update_calls) == 1
        values = update_calls[0][0][1]
        # strain_score is the second parameter (index 1)
        assert values[1] == 92.5

    def test_commits_after_updates(self, garmin_sync, mock_db):
        """The DB transaction is committed after backfill updates."""
        conn, cursor = mock_db
        raw = self._raw_activity()
        cursor.fetchall.return_value = [{'id': 1, 'raw_garmin_data': raw, 'avg_hr': 150, 'duration_minutes': 30.0}]
        garmin_sync.backfill_from_raw_json(conn)
        conn.commit.assert_called_once()

    def test_handles_db_error_gracefully(
        self, garmin_sync, mock_db, capsys
    ):
        """A DB error during backfill is caught, rolled back, and logged."""
        conn, cursor = mock_db
        cursor.fetchall.side_effect = Exception("DB error")
        garmin_sync.backfill_from_raw_json(conn)
        conn.rollback.assert_called_once()
        assert "Backfill failed" in capsys.readouterr().err
