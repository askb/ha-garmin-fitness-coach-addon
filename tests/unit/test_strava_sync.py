# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for strava-sync.py reliability behavior."""

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "pulsecoach"
    / "rootfs"
    / "app"
    / "scripts"
    / "strava-sync.py"
)


@pytest.fixture()
def strava_sync():
    """Import strava-sync.py as a module with network/database deps mocked."""
    with patch.dict(
        sys.modules,
        {"psycopg2": MagicMock(), "requests": MagicMock()},
    ):
        spec = importlib.util.spec_from_file_location("strava_sync", SCRIPT_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        yield mod


@pytest.mark.unit
def test_default_user_id_matches_garmin_sync(strava_sync):
    """Strava rows should share the same seeded app user as Garmin rows."""
    assert strava_sync.USER_ID == "seed-user-001"


@pytest.mark.unit
def test_user_id_env_override_matches_garmin_sync():
    """GARMIN_USER_ID override is honored by Strava sync too."""
    with patch.dict(os.environ, {"GARMIN_USER_ID": "custom-user"}), \
         patch.dict(sys.modules, {"psycopg2": MagicMock(), "requests": MagicMock()}):
        spec = importlib.util.spec_from_file_location("strava_sync_env", SCRIPT_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

    assert mod.USER_ID == "custom-user"


@pytest.mark.unit
def test_migrates_legacy_default_user_rows(strava_sync):
    """Legacy Strava rows under default are moved to the shared user id."""
    db = MagicMock()
    cur = MagicMock()
    cur.rowcount = 2
    db.cursor.return_value = cur

    strava_sync.migrate_legacy_strava_user_id(db)

    sql, params = cur.execute.call_args.args
    assert "UPDATE activity" in sql
    assert params == ("seed-user-001", "default")
    db.commit.assert_called_once()
    db.rollback.assert_not_called()
    cur.close.assert_called_once()


@pytest.mark.unit
def test_sync_activities_uses_savepoints_for_row_failures(strava_sync):
    """A bad row should not roll back previously counted successful rows."""
    db = MagicMock()
    cur = MagicMock()
    db.cursor.return_value = cur

    def execute(sql, params=None):
        if "INSERT INTO activity" in sql and params[1] == 2:
            raise Exception("row failed")

    cur.execute.side_effect = execute
    activities = [
        {"id": 1, "type": "Run", "start_date": "2026-01-01T00:00:00Z"},
        {"id": 2, "type": "Run", "start_date": "2026-01-02T00:00:00Z"},
        {"id": 3, "type": "Run", "start_date": "2026-01-03T00:00:00Z"},
    ]

    synced = strava_sync.sync_activities(db, activities)

    executed_sql = [call.args[0] for call in cur.execute.call_args_list]
    assert synced == 2
    assert "SAVEPOINT strava_activity_upsert" in executed_sql
    assert "ROLLBACK TO SAVEPOINT strava_activity_upsert" in executed_sql
    db.rollback.assert_not_called()
    db.commit.assert_called_once()
