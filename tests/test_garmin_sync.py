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
import math
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
    cursor.fetchone.return_value = None
    cursor.fetchmany.return_value = []
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
            "averageSkinTemperatureCelsius": 35.4,
        }
    }
    client.get_hrv_data.return_value = {"hrvSummary": {"weeklyAvg": 42}}
    client.get_stress_data.return_value = {"avgStressLevel": 35}
    client.get_spo2_data.return_value = {}
    client.get_respiration_data.return_value = {}
    client.get_body_composition.return_value = {}
    client.get_activities.return_value = [
        {
            "activityId": 99001,
            "activityType": {"typeKey": "running", "typeId": "1"},
            "startTimeLocal": "2025-01-15 07:30:00",
            "startTimeGMT": "2025-01-14 21:30:00",
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
# _first_dict — Garmin API list/dict response normaliser
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFirstDict:
    """Regression tests for _first_dict().

    Pins behaviour for the v0.16.18 fix where `garminconnect` started
    returning `[{...}]` instead of `{...}` for training-readiness and
    training-status endpoints, which caused all those columns to stay
    NULL because `data.get("score")` raised AttributeError on a list.
    """

    def test_dict_passes_through(self, garmin_sync):
        result = garmin_sync._first_dict({"score": 75})
        assert result == {"score": 75}

    def test_list_of_one_dict_unwrapped(self, garmin_sync):
        """Latest garminconnect shape: `[{...}]`."""
        result = garmin_sync._first_dict([{"score": 75}])
        assert result == {"score": 75}

    def test_list_with_leading_empty_dict_skipped(self, garmin_sync):
        result = garmin_sync._first_dict([{}, {"score": 75}])
        assert result == {"score": 75}

    def test_none_returns_none(self, garmin_sync):
        assert garmin_sync._first_dict(None) is None

    def test_empty_list_returns_none(self, garmin_sync):
        assert garmin_sync._first_dict([]) is None

    def test_list_of_non_dicts_returns_none(self, garmin_sync):
        assert garmin_sync._first_dict([1, 2, "x"]) is None

    def test_scalar_returns_none(self, garmin_sync):
        assert garmin_sync._first_dict(42) is None

    def test_list_of_empty_dicts_returns_none(self, garmin_sync):
        assert garmin_sync._first_dict([{}, {}]) is None


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

    def test_passes_sleep_dto_skin_temp_to_db(self, garmin_sync, mock_db, mock_client):
        """The preferred sleep DTO skin-temperature value is inserted."""
        conn, cursor = mock_db
        garmin_sync.sync_daily_stats(mock_client, conn, "2025-01-15")
        values = self._get_insert_values(cursor)
        assert values[24] == 35.4

    def test_passes_none_when_skin_temp_missing(self, garmin_sync, mock_db, mock_client):
        """Missing Garmin skin-temperature fields are inserted as NULL/None."""
        conn, cursor = mock_db
        sleep_dto = mock_client.get_sleep_data.return_value["dailySleepDTO"]
        for key in garmin_sync.SKIN_TEMP_KEYS:
            sleep_dto.pop(key, None)
        mock_client.get_stats.return_value.pop("avgSkinTempCelsius", None)

        garmin_sync.sync_daily_stats(mock_client, conn, "2025-01-15")

        values = self._get_insert_values(cursor)
        assert values[24] is None

    def test_falls_back_to_stats_skin_temp(self, garmin_sync, mock_db, mock_client):
        """The stats avgSkinTempCelsius field is used when sleep DTO lacks it."""
        conn, cursor = mock_db
        sleep_dto = mock_client.get_sleep_data.return_value["dailySleepDTO"]
        for key in garmin_sync.SKIN_TEMP_KEYS:
            sleep_dto.pop(key, None)
        mock_client.get_stats.return_value["avgSkinTempCelsius"] = 35.678

        garmin_sync.sync_daily_stats(mock_client, conn, "2025-01-15")

        values = self._get_insert_values(cursor)
        assert values[24] == 35.68

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


    def test_backfill_skin_temp_runs_once(
        self, garmin_sync, mock_db, mock_client, tmp_path
    ):
        """The v0.17.1 backfill re-syncs selected dates and writes marker."""
        conn, cursor = mock_db
        marker = tmp_path / ".skin_temp_backfill_done"
        cursor.fetchall.return_value = [("2025-01-15",), ("2025-01-14",)]

        with patch.object(garmin_sync, "SKIN_TEMP_BACKFILL_MARKER", str(marker)), \
             patch.object(garmin_sync, "sync_daily_stats", return_value=True) as sync_daily:
            garmin_sync.backfill_skin_temp(mock_client, conn)

        assert "skin_temp IS NULL" in cursor.execute.call_args[0][0]
        assert sync_daily.call_args_list == [
            call(mock_client, conn, "2025-01-15"),
            call(mock_client, conn, "2025-01-14"),
        ]
        assert marker.exists()

    def test_backfill_skin_temp_skips_when_marker_exists(
        self, garmin_sync, mock_db, mock_client, tmp_path
    ):
        """Existing sentinel prevents repeated v0.17.1 backfill work."""
        conn, cursor = mock_db
        marker = tmp_path / ".skin_temp_backfill_done"
        marker.write_text("done")

        with patch.object(garmin_sync, "SKIN_TEMP_BACKFILL_MARKER", str(marker)):
            garmin_sync.backfill_skin_temp(mock_client, conn)

        cursor.execute.assert_not_called()

    def test_backfill_skin_temp_does_not_mark_failed_sync(
        self, garmin_sync, mock_db, mock_client, tmp_path
    ):
        """A per-day sync failure leaves the sentinel absent for retry."""
        conn, cursor = mock_db
        marker = tmp_path / ".skin_temp_backfill_done"
        cursor.fetchall.return_value = [("2025-01-15",)]

        with patch.object(garmin_sync, "SKIN_TEMP_BACKFILL_MARKER", str(marker)), \
             patch.object(garmin_sync, "sync_daily_stats", return_value=False):
            garmin_sync.backfill_skin_temp(mock_client, conn)

        assert not marker.exists()


# ---------------------------------------------------------------------------
# sync_activities
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalizeStartedAt:
    """Tests for _normalize_started_at() — UTC-correctness regression.

    Earlier sync code passed Garmin's ``startTimeLocal`` (a TZ-naive
    string in the watch's local time) straight into a ``timestamptz``
    column. Postgres re-interpreted the literal in the session's
    TimeZone (UTC by default), so morning activities for users east
    of UTC were timestamped in the future and were filtered out of
    the home page by ``lte(Activity.startedAt, new Date())``. The
    normalize helper must:

    1. Prefer ``startTimeGMT``.
    2. Stamp it with an explicit ``+00:00`` offset.
    3. Fall back to ``startTimeLocal`` only when ``startTimeGMT`` is
       absent.
    """

    def test_prefers_gmt_and_appends_utc_offset(self, garmin_sync):
        act = {
            "startTimeGMT": "2026-05-17 09:00:00",
            "startTimeLocal": "2026-05-17 19:00:00",  # AEST same instant
        }
        assert garmin_sync._normalize_started_at(act) == "2026-05-17 09:00:00+00:00"

    def test_falls_back_to_local_when_gmt_missing(self, garmin_sync):
        act = {"startTimeLocal": "2026-05-17 19:00:00"}
        # Legacy behaviour preserved when GMT is unavailable; we'd
        # rather store *something* than NULL on these rare rows.
        assert garmin_sync._normalize_started_at(act) == "2026-05-17 19:00:00"

    def test_returns_none_when_both_missing(self, garmin_sync):
        assert garmin_sync._normalize_started_at({}) is None

    def test_does_not_double_stamp_when_offset_already_present(self, garmin_sync):
        # Defensive: future Garmin client versions may include an offset.
        act = {"startTimeGMT": "2026-05-17 09:00:00+00:00"}
        assert garmin_sync._normalize_started_at(act) == "2026-05-17 09:00:00+00:00"

    def test_does_not_double_stamp_when_z_suffix_present(self, garmin_sync):
        act = {"startTimeGMT": "2026-05-17T09:00:00Z"}
        assert garmin_sync._normalize_started_at(act) == "2026-05-17T09:00:00Z"

    def test_does_not_double_stamp_when_negative_offset_present(self, garmin_sync):
        # Defensive: a future Garmin build may emit a non-UTC offset.
        # The trailing-offset detector must not be fooled by the '-'
        # characters inside the date portion.
        act = {"startTimeGMT": "2026-05-17 04:00:00-05:00"}
        assert (
            garmin_sync._normalize_started_at(act)
            == "2026-05-17 04:00:00-05:00"
        )

    def test_does_not_double_stamp_when_compact_offset_present(self, garmin_sync):
        act = {"startTimeGMT": "2026-05-17 04:00:00-0500"}
        assert (
            garmin_sync._normalize_started_at(act)
            == "2026-05-17 04:00:00-0500"
        )

    def test_blank_gmt_falls_back_to_local(self, garmin_sync):
        act = {
            "startTimeGMT": "   ",
            "startTimeLocal": "2026-05-17 19:00:00",
        }
        assert garmin_sync._normalize_started_at(act) == "2026-05-17 19:00:00"


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

    def test_started_at_uses_gmt_with_utc_offset(
        self, garmin_sync, mock_db, mock_client
    ):
        """started_at hits the DB as the UTC instant, never the local string.

        Regression for the "missing recent workouts" bug where AEST
        morning activities were timestamped in the future and filtered
        out by the app router. The INSERT must carry the GMT field
        with an explicit ``+00:00`` so Postgres always parses it as
        UTC regardless of the database session's TimeZone.
        """
        conn, cursor = mock_db
        garmin_sync.sync_activities(mock_client, conn, days=7)
        insert_call = self._get_activity_insert_call(cursor)
        assert insert_call is not None
        values = insert_call[0][1]
        # started_at is the 5th positional in the INSERT (after
        # user_id, garmin_activity_id, sport_type, sub_type).
        assert "2025-01-14 21:30:00+00:00" in values
        # And the local-time string must NOT have leaked through.
        assert "2025-01-15 07:30:00" not in values

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

    def test_unwraps_list_of_list_response(
        self, garmin_sync, mock_db, mock_client
    ):
        """Garmin sometimes returns activities as `[[{...}]]`; unwrap it."""
        conn, cursor = mock_db
        original = mock_client.get_activities.return_value
        mock_client.get_activities.side_effect = [
            [original],  # list-of-list wrapper
            [],
        ]
        garmin_sync.sync_activities(mock_client, conn, days=7)
        insert_calls = [
            c for c in cursor.execute.call_args_list
            if "INSERT INTO activity" in c[0][0]
        ]
        assert len(insert_calls) == len(original)

    def test_skips_non_dict_activity_entries(
        self, garmin_sync, mock_db, mock_client, capsys
    ):
        """Garbled entries in the activities array are skipped, not fatal."""
        conn, cursor = mock_db
        good = mock_client.get_activities.return_value[0]
        mock_client.get_activities.side_effect = [
            ["not-a-dict", None, good],
            [],
        ]
        garmin_sync.sync_activities(mock_client, conn, days=7)
        insert_calls = [
            c for c in cursor.execute.call_args_list
            if "INSERT INTO activity" in c[0][0]
        ]
        assert len(insert_calls) == 1
        err = capsys.readouterr().err
        assert "Skipping non-dict activity entry" in err

    def test_per_row_failure_does_not_abort_batch(
        self, garmin_sync, mock_db, mock_client, capsys
    ):
        """A single row exception is logged and rolled back; siblings still sync."""
        conn, cursor = mock_db
        good = dict(mock_client.get_activities.return_value[0])
        bad = dict(good)
        bad["activityId"] = 99002

        original_execute = cursor.execute

        def selective_execute(sql, params=None):
            if (
                params is not None
                and len(params) > 1
                and params[1] == "99002"
                and "INSERT INTO activity" in sql
            ):
                raise RuntimeError("simulated row failure")
            return original_execute(sql, params)

        cursor.execute = MagicMock(side_effect=selective_execute)
        mock_client.get_activities.side_effect = [[bad, good], []]
        garmin_sync.sync_activities(mock_client, conn, days=7)
        err = capsys.readouterr().err
        assert "Failed to upsert activity 99002" in err
        # Per-row failure rolls back to the savepoint (not the whole batch)
        # so earlier successful upserts are preserved on commit.
        executed_sql = [
            c[0][0] for c in cursor.execute.call_args_list
            if isinstance(c[0][0], str)
        ]
        assert any("SAVEPOINT activity_upsert" in s for s in executed_sql)
        assert any(
            "ROLLBACK TO SAVEPOINT activity_upsert" in s for s in executed_sql
        )
        assert conn.commit.called

    def test_good_then_bad_then_good_persists_good_rows(
        self, garmin_sync, mock_db, mock_client, capsys
    ):
        """Good rows before AND after a bad row in the same batch survive.

        Regression for the bug where a per-row failure called
        ``db.rollback()`` on the whole connection, wiping previously
        successful upserts within the same batch.
        """
        conn, cursor = mock_db
        base = mock_client.get_activities.return_value[0]
        good1 = dict(base)
        good1["activityId"] = 99001
        bad = dict(base)
        bad["activityId"] = 99002
        good2 = dict(base)
        good2["activityId"] = 99003

        original_execute = cursor.execute

        def selective_execute(sql, params=None):
            if (
                params is not None
                and len(params) > 1
                and params[1] == "99002"
                and "INSERT INTO activity" in sql
            ):
                raise RuntimeError("simulated row failure")
            return original_execute(sql, params)

        cursor.execute = MagicMock(side_effect=selective_execute)
        mock_client.get_activities.side_effect = [[good1, bad, good2], []]
        garmin_sync.sync_activities(mock_client, conn, days=7)

        insert_calls = [
            c for c in cursor.execute.call_args_list
            if isinstance(c[0][0], str) and "INSERT INTO activity" in c[0][0]
        ]
        inserted_ids = {c[0][1][1] for c in insert_calls}
        # Both good rows were attempted (and the SAVEPOINT for the bad row
        # was rolled back without aborting the surrounding commit).
        assert "99001" in inserted_ids
        assert "99003" in inserted_ids
        # The connection-level rollback() was NOT called — only the
        # per-row SAVEPOINT was rolled back.
        assert not conn.rollback.called
        assert conn.commit.called


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
        # Profile age = 35 (used to compute age-predicted HRmax)
        cursor.fetchone.return_value = (35,)
        # Provide one resting-HR row (resting_hr=58)
        cursor.fetchmany.side_effect = [
            [('2025-01-15', 58)],  # first fetchmany batch
            [],                    # second call → stop loop
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
        # age=35 fetched from the profile table → Tanaka HRmax = 208 - (0.7 * 35)
        cursor.fetchone.return_value = (35,)
        cursor.fetchmany.side_effect = [
            [('2025-01-15', 58)],
            [],
        ]
        garmin_sync.sync_vo2max(mock_client, conn, days=1)
        expected_vo2 = round(15.3 * ((208 - (0.7 * 35)) / 58), 1)
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
        cursor.fetchall.return_value = [(1, raw, 150, 30.0)]
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
        cursor.fetchall.return_value = [(1, raw, 150, 30.0)]
        garmin_sync.backfill_from_raw_json(conn)
        update_calls = [
            c for c in cursor.execute.call_args_list
            if "UPDATE activity" in c[0][0]
        ]
        assert len(update_calls) == 1
        values = update_calls[0][0][1]
        # trimp_score is the third parameter (index 2)
        trimp = values[2]
        delta_ratio = (150 - 60) / (190 - 60)
        expected = round(30 * delta_ratio * math.exp(1.92 * delta_ratio), 1)
        assert trimp == expected

    def test_stores_strain_score_from_raw_data(self, garmin_sync, mock_db):
        """activityTrainingLoad in raw JSON is stored as strain_score."""
        conn, cursor = mock_db
        raw = self._raw_activity(activityTrainingLoad=92.5)
        cursor.fetchall.return_value = [(1, raw, 150, 30.0)]
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
        cursor.fetchall.return_value = [(1, raw, 150, 30.0)]
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


# ---------------------------------------------------------------------------
# Timezone handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTimezone:
    """Tests for timezone-aware date boundaries and sleep time extraction."""

    def test_extract_sleep_time_local_timestamp(self, garmin_sync):
        """_extract_sleep_time extracts local wall-clock time from Garmin Local timestamps.

        Garmin 'Local' timestamps encode local wall-clock time as if it were UTC,
        so we construct the test epoch ms using UTC to match.
        """
        from datetime import datetime as dt, timezone as tz
        # 22:30 local = 1350 minutes from midnight
        ts_ms = int(dt(2025, 1, 15, 22, 30, tzinfo=tz.utc).timestamp() * 1000)
        sleep_dto = {"sleepStartTimestampLocal": ts_ms}
        result = garmin_sync._extract_sleep_time(sleep_dto, "sleepStartTimestampLocal")
        assert result == "1350"

    def test_extract_sleep_time_early_morning(self, garmin_sync):
        """_extract_sleep_time handles early morning wake times (e.g., 06:15)."""
        from datetime import datetime as dt, timezone as tz
        ts_ms = int(dt(2025, 1, 16, 6, 15, tzinfo=tz.utc).timestamp() * 1000)
        sleep_dto = {"sleepEndTimestampLocal": ts_ms}
        result = garmin_sync._extract_sleep_time(sleep_dto, "sleepEndTimestampLocal")
        assert result == "375"  # 6*60+15

    def test_extract_sleep_time_none_returns_none(self, garmin_sync):
        """_extract_sleep_time returns None for missing timestamps."""
        assert garmin_sync._extract_sleep_time({}, "sleepStartTimestampLocal") is None
        assert garmin_sync._extract_sleep_time({"sleepStartTimestampLocal": None}, "sleepStartTimestampLocal") is None

    def test_user_today_respects_timezone(self, garmin_sync):
        """_user_today returns a date consistent with the configured timezone.

        For the default UTC config, _user_today() should match UTC date.
        We also verify it shifts correctly for a non-UTC timezone by
        temporarily patching USER_TZ.
        """
        from datetime import date, datetime, timezone as tz
        from zoneinfo import ZoneInfo
        from unittest.mock import patch

        # Default: UTC — should match UTC date
        utc_today = datetime.now(tz.utc).date()
        assert garmin_sync._user_today() == utc_today

        # Patch to a far-ahead timezone and verify date can differ from UTC
        with patch.object(garmin_sync, 'USER_TZ', ZoneInfo("Pacific/Auckland")):
            nz_today = datetime.now(ZoneInfo("Pacific/Auckland")).date()
            assert garmin_sync._user_today() == nz_today

    def test_user_tz_defaults_to_utc(self, garmin_sync):
        """USER_TZ defaults to UTC when no environment variable is set."""
        # Compare by key name rather than identity (ZoneInfo caching not guaranteed)
        assert str(garmin_sync.USER_TZ) == "UTC"


class TestMatviewRefresh:
    """Tests for materialized view refresh integration."""

    def test_refresh_matview_success(self, garmin_sync):
        """_refresh_matview calls the refresh function and commits."""
        from unittest.mock import MagicMock
        db = MagicMock()
        cur = MagicMock()
        db.cursor.return_value = cur

        garmin_sync._refresh_matview(db)

        cur.execute.assert_called_once_with("SELECT refresh_daily_athlete_summary()")
        db.commit.assert_called_once()
        cur.close.assert_called_once()

    def test_refresh_matview_error_rolls_back(self, garmin_sync):
        """_refresh_matview rolls back on error without raising."""
        from unittest.mock import MagicMock
        db = MagicMock()
        cur = MagicMock()
        db.cursor.return_value = cur
        cur.execute.side_effect = Exception("relation does not exist")

        # Should not raise
        garmin_sync._refresh_matview(db)

        db.rollback.assert_called_once()
        db.commit.assert_not_called()
        cur.close.assert_called_once()
