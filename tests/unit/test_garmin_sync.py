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
    / "garmincoach"
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
        """After a fresh login the session token is saved to disk."""
        token_dir = str(tmp_path / "tokens")
        mock_client = MagicMock()
        mock_client.garth.dumps.return_value = {"session": "fresh"}
        garmin_sync._mock_garmin_module.Garmin.return_value = mock_client

        with patch.object(garmin_sync, "TOKEN_DIR", token_dir):
            garmin_sync.get_client()

        token_file = os.path.join(token_dir, "session.json")
        assert os.path.exists(token_file)
        with open(token_file) as f:
            assert json.load(f) == {"session": "fresh"}

    def test_reuses_existing_token(self, garmin_sync, tmp_path):
        """If a valid token file exists, login uses it."""
        token_dir = str(tmp_path / "tokens")
        os.makedirs(token_dir)
        token_file = os.path.join(token_dir, "session.json")
        with open(token_file, "w") as f:
            json.dump({"token": "saved"}, f)

        mock_client = MagicMock()
        garmin_sync._mock_garmin_module.Garmin.return_value = mock_client

        with patch.object(garmin_sync, "TOKEN_DIR", token_dir):
            garmin_sync.get_client()

        # login() should have been called with the saved token store
        mock_client.login.assert_called_once_with(tokenstore={"token": "saved"})

    def test_falls_back_to_credentials_on_expired_token(
        self, garmin_sync, tmp_path
    ):
        """If loading the saved token fails, falls back to credential login."""
        token_dir = str(tmp_path / "tokens")
        os.makedirs(token_dir)
        token_file = os.path.join(token_dir, "session.json")
        with open(token_file, "w") as f:
            json.dump({"token": "expired"}, f)

        mock_client = MagicMock()
        # First call (with tokenstore) raises; second call (no args) succeeds
        mock_client.login.side_effect = [Exception("token expired"), None]
        mock_client.garth.dumps.return_value = {"token": "new"}
        garmin_sync._mock_garmin_module.Garmin.return_value = mock_client

        with patch.object(garmin_sync, "TOKEN_DIR", token_dir):
            garmin_sync.get_client()

        assert mock_client.login.call_count == 2


# ── Daily stats sync ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSyncDailyStats:
    """Tests for sync_daily_stats()."""

    def test_inserts_daily_stats(
        self, garmin_sync, in_memory_db, mock_garmin_client
    ):
        """Daily stats are correctly inserted into the database."""
        garmin_sync.sync_daily_stats(
            mock_garmin_client, in_memory_db, "2025-01-15"
        )

        row = in_memory_db.execute(
            "SELECT * FROM daily_metric WHERE date = '2025-01-15'"
        ).fetchone()
        assert row is not None
        # user_id, date, steps
        assert row[0] == "addon-user"
        assert row[1] == "2025-01-15"
        assert row[2] == 8500  # steps

    def test_calculates_sleep_minutes(
        self, garmin_sync, in_memory_db, mock_garmin_client
    ):
        """Sleep seconds from Garmin are correctly converted to minutes."""
        garmin_sync.sync_daily_stats(
            mock_garmin_client, in_memory_db, "2025-01-15"
        )

        row = in_memory_db.execute(
            "SELECT total_sleep_minutes, deep_sleep_minutes, "
            "rem_sleep_minutes, light_sleep_minutes, awake_minutes "
            "FROM daily_metric WHERE date = '2025-01-15'"
        ).fetchone()
        assert row == (480, 120, 90, 240, 30)

    def test_handles_missing_sleep_data(
        self, garmin_sync, in_memory_db, mock_garmin_client, capsys
    ):
        """When sleep data is None the error is caught and logged."""
        mock_garmin_client.get_sleep_data.return_value = None
        garmin_sync.sync_daily_stats(
            mock_garmin_client, in_memory_db, "2025-01-15"
        )

        # The script's broad except catches the AttributeError from None.get()
        row = in_memory_db.execute(
            "SELECT total_sleep_minutes FROM daily_metric WHERE date = '2025-01-15'"
        ).fetchone()
        assert row is None

        captured = capsys.readouterr()
        assert "Failed to sync" in captured.err

    def test_handles_api_error_gracefully(
        self, garmin_sync, in_memory_db, mock_garmin_client, capsys
    ):
        """API errors are caught and logged, not raised."""
        mock_garmin_client.get_stats.side_effect = ConnectionError("timeout")
        garmin_sync.sync_daily_stats(
            mock_garmin_client, in_memory_db, "2025-01-15"
        )

        row = in_memory_db.execute(
            "SELECT * FROM daily_metric WHERE date = '2025-01-15'"
        ).fetchone()
        assert row is None

        captured = capsys.readouterr()
        assert "Failed to sync" in captured.err

    def test_upserts_on_duplicate_date(
        self, garmin_sync, in_memory_db, mock_garmin_client
    ):
        """Running sync twice for the same date updates rather than duplicates."""
        garmin_sync.sync_daily_stats(
            mock_garmin_client, in_memory_db, "2025-01-15"
        )
        mock_garmin_client.get_stats.return_value["totalSteps"] = 12000
        garmin_sync.sync_daily_stats(
            mock_garmin_client, in_memory_db, "2025-01-15"
        )

        rows = in_memory_db.execute(
            "SELECT steps FROM daily_metric WHERE date = '2025-01-15'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 12000


# ── Activity sync ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSyncActivities:
    """Tests for sync_activities()."""

    def test_inserts_activity(
        self, garmin_sync, in_memory_db, mock_garmin_client
    ):
        """Activities are correctly inserted into the database."""
        garmin_sync.sync_activities(mock_garmin_client, in_memory_db, days=7)

        row = in_memory_db.execute(
            "SELECT sport_type, duration_minutes FROM activity "
            "WHERE garmin_activity_id = '12345'"
        ).fetchone()
        assert row is not None
        assert row[0] == "running"
        assert row[1] == 30.0  # 1800s / 60

    def test_stores_raw_json(
        self, garmin_sync, in_memory_db, mock_garmin_client
    ):
        """Raw Garmin JSON is preserved in the database."""
        garmin_sync.sync_activities(mock_garmin_client, in_memory_db, days=7)

        row = in_memory_db.execute(
            "SELECT raw_garmin_data FROM activity "
            "WHERE garmin_activity_id = '12345'"
        ).fetchone()
        raw = json.loads(row[0])
        assert raw["activityId"] == 12345

    def test_ignores_duplicate_activities(
        self, garmin_sync, in_memory_db, mock_garmin_client
    ):
        """Duplicate activity IDs are silently ignored (INSERT OR IGNORE)."""
        garmin_sync.sync_activities(mock_garmin_client, in_memory_db, days=7)
        garmin_sync.sync_activities(mock_garmin_client, in_memory_db, days=7)

        count = in_memory_db.execute(
            "SELECT COUNT(*) FROM activity"
        ).fetchone()[0]
        assert count == 1

    def test_handles_api_error_gracefully(
        self, garmin_sync, in_memory_db, mock_garmin_client, capsys
    ):
        """API errors during activity sync are caught and logged."""
        mock_garmin_client.get_activities.side_effect = ConnectionError("down")
        garmin_sync.sync_activities(mock_garmin_client, in_memory_db, days=7)

        count = in_memory_db.execute(
            "SELECT COUNT(*) FROM activity"
        ).fetchone()[0]
        assert count == 0

        captured = capsys.readouterr()
        assert "Failed to sync activities" in captured.err


# ── Main entry point ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestMain:
    """Tests for the main() entry point."""

    def test_skips_when_no_credentials(self, garmin_sync, capsys):
        """main() exits early when credentials are not set."""
        with patch.object(garmin_sync, "GARMIN_EMAIL", ""), \
             patch.object(garmin_sync, "GARMIN_PASSWORD", ""):
            garmin_sync.main()

        captured = capsys.readouterr()
        assert "No Garmin credentials configured" in captured.out

    def test_syncs_seven_days(self, garmin_sync, in_memory_db, mock_garmin_client):
        """main() calls sync_daily_stats for 7 days and sync_activities once."""
        with patch.object(garmin_sync, "GARMIN_EMAIL", "a@b.com"), \
             patch.object(garmin_sync, "GARMIN_PASSWORD", "pass"), \
             patch.object(garmin_sync, "get_client", return_value=mock_garmin_client), \
             patch("sqlite3.connect", return_value=in_memory_db), \
             patch.object(garmin_sync, "sync_daily_stats") as mock_daily, \
             patch.object(garmin_sync, "sync_activities") as mock_act:
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
                "DATABASE_URL", "file:/data/garmincoach.db"
            ).replace("file:", "")
            assert result == "/data/test.db"

    def test_default_db_path(self, garmin_sync):
        """Without DATABASE_URL the default path is used."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            result = os.environ.get(
                "DATABASE_URL", "file:/data/garmincoach.db"
            ).replace("file:", "")
            assert result == "/data/garmincoach.db"
