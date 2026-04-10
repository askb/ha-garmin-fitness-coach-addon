# SPDX-FileCopyrightText: 2025 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Shared pytest fixtures for pulsecoach tests."""

import json
import os
import sqlite3
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def tmp_data_dir(tmp_path):
    """Provide a temporary data directory and set DATABASE_URL."""
    db_path = str(tmp_path / "pulsecoach.db")
    with patch.dict(os.environ, {"DATABASE_URL": f"file:{db_path}"}):
        yield tmp_path, db_path


@pytest.fixture()
def tmp_token_dir(tmp_path):
    """Provide a temporary token directory."""
    token_dir = tmp_path / "garmin-tokens"
    token_dir.mkdir()
    return str(token_dir)


@pytest.fixture()
def in_memory_db():
    """Provide an in-memory SQLite database with the expected schema."""
    db = sqlite3.connect(":memory:")
    db.execute("""
        CREATE TABLE daily_metric (
            user_id TEXT,
            date TEXT,
            steps INTEGER,
            calories INTEGER,
            resting_hr INTEGER,
            max_hr INTEGER,
            total_sleep_minutes INTEGER,
            deep_sleep_minutes INTEGER,
            rem_sleep_minutes INTEGER,
            light_sleep_minutes INTEGER,
            awake_minutes INTEGER,
            sleep_score REAL,
            hrv REAL,
            stress_score REAL,
            body_battery_start INTEGER,
            body_battery_end INTEGER,
            floors_climbed INTEGER,
            intensity_minutes INTEGER,
            synced_at TEXT,
            PRIMARY KEY (user_id, date)
        )
    """)
    db.execute("""
        CREATE TABLE activity (
            user_id TEXT,
            garmin_activity_id TEXT,
            sport_type TEXT,
            sub_type TEXT,
            started_at TEXT,
            duration_minutes REAL,
            distance_meters REAL,
            avg_hr INTEGER,
            max_hr INTEGER,
            calories INTEGER,
            avg_pace_sec_per_km REAL,
            aerobic_te REAL,
            anaerobic_te REAL,
            synced_at TEXT,
            raw_garmin_data TEXT,
            PRIMARY KEY (user_id, garmin_activity_id)
        )
    """)
    yield db
    db.close()


@pytest.fixture()
def mock_garmin_client():
    """Return a MagicMock that mimics the garminconnect.Garmin client."""
    client = MagicMock()
    client.garth = MagicMock()
    client.garth.dumps.return_value = {"token": "fake-session-data"}

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
            "sleepTimeSeconds": 28800,
            "deepSleepSeconds": 7200,
            "remSleepSeconds": 5400,
            "lightSleepSeconds": 14400,
            "awakeSleepSeconds": 1800,
            "sleepScores": {"overall": {"value": 82}},
        }
    }
    client.get_hrv_data.return_value = {
        "hrvSummary": {"weeklyAvg": 42}
    }
    client.get_stress_data.return_value = {
        "averageStressLevel": 35
    }
    client.get_activities.return_value = [
        {
            "activityId": 12345,
            "activityType": {"typeKey": "running", "typeId": "1"},
            "startTimeLocal": "2025-01-15 07:30:00",
            "duration": 1800.0,
            "distance": 5000.0,
            "averageHR": 150,
            "maxHR": 175,
            "calories": 400,
            "averageSpeed": 320.0,
            "aerobicTrainingEffect": 3.5,
            "anaerobicTrainingEffect": 1.2,
        },
    ]
    return client


@pytest.fixture()
def mock_pg_db():
    """Return a mock psycopg2 connection and cursor (avoids PostgreSQL-specific SQL issues)."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


@pytest.fixture()
def garmin_env():
    """Set Garmin credential environment variables for testing."""
    env = {
        "GARMIN_EMAIL": "test@example.com",
        "GARMIN_PASSWORD": "fake-password",
    }
    with patch.dict(os.environ, env):
        yield env


@pytest.fixture()
def supervisor_env():
    """Set Home Assistant supervisor environment variables."""
    env = {
        "SUPERVISOR_TOKEN": "fake-supervisor-token",
        "HA_BASE_URL": "http://supervisor/core",
        "AI_BACKEND": "ha_conversation",
    }
    with patch.dict(os.environ, env):
        yield env
