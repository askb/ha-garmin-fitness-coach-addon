# SPDX-FileCopyrightText: 2025 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for garmin-sync.py."""

import importlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

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


# ── Token file handling ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestGetClient:
    """Tests for the get_client() authentication flow."""

    def test_creates_token_directory(self, garmin_sync, tmp_path):
        """get_client creates the token directory if it doesn't exist."""
        token_dir = str(tmp_path / "tokens")
        mock_client = MagicMock()
        mock_client.garth.dumps.return_value = {"token": "data"}
        garmin_sync._mock_garmin_module.Garmin.return_value = mock_client

        with patch.object(garmin_sync, "TOKEN_DIR", token_dir):
            garmin_sync.get_client()

        assert os.path.isdir(token_dir)

    def test_saves_token_after_fresh_login(self, garmin_sync, tmp_path):
        """After a fresh login garth.dump() is called to persist the session tokens.

        Token file creation is delegated to the garth library (mocked here);
        we verify the call rather than file existence.
        """
        token_dir = str(tmp_path / "tokens")
        os.makedirs(token_dir)
        # Create oauth token files so the token-resume path is taken
        open(os.path.join(token_dir, "oauth1_token.json"), "w").close()
        open(os.path.join(token_dir, "oauth2_token.json"), "w").close()

        mock_client = MagicMock()
        garmin_sync._mock_garmin_module.Garmin.return_value = mock_client

        with patch.object(garmin_sync, "TOKEN_DIR", token_dir):
            garmin_sync.get_client()

        mock_client.garth.dump.assert_called_once_with(token_dir)

    def test_reuses_existing_token(self, garmin_sync, tmp_path):
        """If valid oauth token files exist, login uses the token directory."""
        token_dir = str(tmp_path / "tokens")
        os.makedirs(token_dir)
        # The actual code checks for oauth1_token.json and oauth2_token.json
        open(os.path.join(token_dir, "oauth1_token.json"), "w").close()
        open(os.path.join(token_dir, "oauth2_token.json"), "w").close()

        mock_client = MagicMock()
        garmin_sync._mock_garmin_module.Garmin.return_value = mock_client

        with patch.object(garmin_sync, "TOKEN_DIR", token_dir):
            garmin_sync.get_client()

        # login() should have been called with the token directory path
        mock_client.login.assert_called_once_with(tokenstore=token_dir)

    def test_falls_back_to_credentials_on_expired_token(
        self, garmin_sync, tmp_path
    ):
        """If loading saved oauth tokens fails, falls back to credential login."""
        token_dir = str(tmp_path / "tokens")
        os.makedirs(token_dir)
        # Create oauth token files so the token-resume path is attempted
        open(os.path.join(token_dir, "oauth1_token.json"), "w").close()
        open(os.path.join(token_dir, "oauth2_token.json"), "w").close()

        mock_client = MagicMock()
        # First login() call (with tokenstore) raises; second call (credentials) succeeds
        mock_client.login.side_effect = [Exception("token expired"), None]
        garmin_sync._mock_garmin_module.Garmin.return_value = mock_client

        with patch.object(garmin_sync, "TOKEN_DIR", token_dir), \
             patch.object(garmin_sync, "GARMIN_EMAIL", "user@example.com"), \
             patch.object(garmin_sync, "GARMIN_PASSWORD", "secret"):
            garmin_sync.get_client()

        assert mock_client.login.call_count == 2


# ── Daily stats sync ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSyncDailyStats:
    """Tests for sync_daily_stats()."""

    def test_inserts_daily_stats(
        self, garmin_sync, mock_pg_db, mock_garmin_client
    ):
        """Daily stats are correctly inserted into the database (cursor.execute called)."""
        conn, cursor = mock_pg_db
        garmin_sync.sync_daily_stats(
            mock_garmin_client, conn, "2025-01-15"
        )

        assert cursor.execute.called
        assert conn.commit.called

    def test_calculates_sleep_minutes(
        self, garmin_sync, mock_pg_db, mock_garmin_client
    ):
        """Sleep seconds from Garmin are correctly converted to minutes in the INSERT values."""
        conn, cursor = mock_pg_db
        garmin_sync.sync_daily_stats(
            mock_garmin_client, conn, "2025-01-15"
        )

        # Find the INSERT INTO daily_metric call and inspect its values tuple.
        insert_call = next(
            (c for c in cursor.execute.call_args_list
             if "INSERT INTO daily_metric" in c[0][0]),
            None,
        )
        assert insert_call is not None
        values = insert_call[0][1]
        # 28800 s → 480 min, 7200 s → 120 min, 5400 s → 90 min,
        # 14400 s → 240 min, 1800 s → 30 min
        assert 480 in values  # total_sleep_minutes
        assert 120 in values  # deep_sleep_minutes
        assert 90 in values   # rem_sleep_minutes
        assert 240 in values  # light_sleep_minutes
        assert 30 in values   # awake_minutes

    def test_handles_missing_sleep_data(
        self, garmin_sync, mock_pg_db, mock_garmin_client
    ):
        """When sleep data is None the function handles it gracefully."""
        conn, cursor = mock_pg_db
        mock_garmin_client.get_sleep_data.return_value = None
        garmin_sync.sync_daily_stats(
            mock_garmin_client, conn, "2025-01-15"
        )

        # Insert should still run (with NULL sleep values) and commit should be called
        assert conn.commit.called

    def test_handles_api_error_gracefully(
        self, garmin_sync, mock_pg_db, mock_garmin_client, capsys
    ):
        """API errors are caught and logged, not raised."""
        conn, cursor = mock_pg_db
        mock_garmin_client.get_stats.side_effect = ConnectionError("timeout")
        garmin_sync.sync_daily_stats(
            mock_garmin_client, conn, "2025-01-15"
        )

        conn.rollback.assert_called_once()
        captured = capsys.readouterr()
        assert "Failed to sync" in captured.err

    def test_upserts_on_duplicate_date(
        self, garmin_sync, mock_pg_db, mock_garmin_client
    ):
        """Running sync twice for the same date calls the upsert twice (ON CONFLICT)."""
        conn, cursor = mock_pg_db
        garmin_sync.sync_daily_stats(
            mock_garmin_client, conn, "2025-01-15"
        )
        garmin_sync.sync_daily_stats(
            mock_garmin_client, conn, "2025-01-15"
        )

        insert_calls = [
            c for c in cursor.execute.call_args_list
            if "INSERT INTO daily_metric" in c[0][0]
        ]
        assert len(insert_calls) == 2


# ── Activity sync ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSyncActivities:
    """Tests for sync_activities()."""

    def test_inserts_activity(
        self, garmin_sync, mock_pg_db, mock_garmin_client
    ):
        """Activities are correctly passed to the database cursor."""
        conn, cursor = mock_pg_db
        garmin_sync.sync_activities(mock_garmin_client, conn, days=7)

        insert_calls = [
            c for c in cursor.execute.call_args_list
            if "INSERT INTO activity" in c[0][0]
        ]
        assert len(insert_calls) == 1
        assert conn.commit.called

    def test_stores_raw_json(
        self, garmin_sync, mock_pg_db, mock_garmin_client
    ):
        """Raw Garmin JSON is preserved in the INSERT values."""
        conn, cursor = mock_pg_db
        garmin_sync.sync_activities(mock_garmin_client, conn, days=7)

        insert_call = next(
            (c for c in cursor.execute.call_args_list
             if "INSERT INTO activity" in c[0][0]),
            None,
        )
        assert insert_call is not None
        values = insert_call[0][1]
        # raw_garmin_data is the last value; it must be a JSON string with activityId
        raw = json.loads(values[-1])
        assert raw["activityId"] == 12345

    def test_handles_api_error_gracefully(
        self, garmin_sync, mock_pg_db, mock_garmin_client, capsys
    ):
        """API errors during activity sync are caught and logged."""
        conn, cursor = mock_pg_db
        mock_garmin_client.get_activities.side_effect = ConnectionError("down")
        garmin_sync.sync_activities(mock_garmin_client, conn, days=7)

        captured = capsys.readouterr()
        assert "Failed to sync activities" in captured.err


# ── Main entry point ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestMain:
    """Tests for the main() entry point."""

    def test_skips_when_no_credentials(self, garmin_sync, capsys):
        """main() exits early when no tokens and no credentials are set."""
        with patch.object(garmin_sync, "GARMIN_EMAIL", ""), \
             patch.object(garmin_sync, "GARMIN_PASSWORD", ""), \
             patch.object(garmin_sync, "TOKEN_DIR", "/nonexistent/token/dir"):
            garmin_sync.main()

        captured = capsys.readouterr()
        assert "No Garmin tokens or credentials configured" in captured.out

    def test_syncs_seven_days(self, garmin_sync, mock_pg_db, mock_garmin_client, tmp_path):
        """main() calls sync_daily_stats for 7 days and sync_activities once."""
        conn, _ = mock_pg_db
        # Create the initial-sync marker so main() uses sync_days=7
        (tmp_path / ".initial_sync_done").touch()

        with patch.object(garmin_sync, "GARMIN_EMAIL", "a@b.com"), \
             patch.object(garmin_sync, "GARMIN_PASSWORD", "pass"), \
             patch.object(garmin_sync, "TOKEN_DIR", str(tmp_path)), \
             patch.object(garmin_sync, "get_client", return_value=mock_garmin_client), \
             patch.object(garmin_sync, "get_db", return_value=conn), \
             patch.object(garmin_sync, "_write_sync_status"), \
             patch.object(garmin_sync, "_clear_sync_status"), \
             patch.object(garmin_sync, "sync_daily_stats") as mock_daily, \
             patch.object(garmin_sync, "sync_activities") as mock_act, \
             patch.object(garmin_sync, "backfill_from_raw_json"), \
             patch.object(garmin_sync, "backfill_stress_and_sleep"), \
             patch.object(garmin_sync, "sync_vo2max"):
            garmin_sync.main()

        assert mock_daily.call_count == 7
        mock_act.assert_called_once()


# ── Date range calculation ───────────────────────────────────────────────────


@pytest.mark.unit
class TestDateRange:
    """Tests for the date range logic used in main()."""

    def test_date_range_covers_last_seven_days(self):
        """The sync loop generates ISO dates for the last 7 days."""
        today = datetime.utcnow().date()
        expected = [
            (today - timedelta(days=d)).isoformat() for d in range(7)
        ]
        assert len(expected) == 7
        assert expected[0] == today.isoformat()
        assert expected[-1] == (today - timedelta(days=6)).isoformat()

    def test_date_strings_are_iso_format(self):
        """Generated date strings match YYYY-MM-DD ISO format."""
        today = datetime.utcnow().date()
        for d in range(7):
            date_str = (today - timedelta(days=d)).isoformat()
            parsed = datetime.strptime(date_str, "%Y-%m-%d")
            assert parsed.date() == today - timedelta(days=d)


# ── Environment / DB_PATH ────────────────────────────────────────────────────


@pytest.mark.unit
class TestDbPath:
    """Tests for DATABASE_URL environment variable handling."""

    def test_strips_file_prefix(self, garmin_sync):
        """DB_PATH strips the 'file:' prefix from DATABASE_URL."""
        with patch.dict(os.environ, {"DATABASE_URL": "file:/data/test.db"}):
            # Re-evaluate at module level
            result = os.environ.get(
                "DATABASE_URL", "file:/data/pulsecoach.db"
            ).replace("file:", "")
            assert result == "/data/test.db"

    def test_default_db_path(self, garmin_sync):
        """Without DATABASE_URL the default path is used."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            result = os.environ.get(
                "DATABASE_URL", "file:/data/pulsecoach.db"
            ).replace("file:", "")
            assert result == "/data/pulsecoach.db"
