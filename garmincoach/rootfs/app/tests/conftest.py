"""Shared pytest fixtures for GarminCoach tests."""
import json
import os
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def db_mock():
    """Mock psycopg2 database connection."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.__enter__ = lambda s: cursor
    cursor.__exit__ = MagicMock(return_value=False)
    return conn, cursor


@pytest.fixture
def sample_stats():
    """Sample Garmin daily stats response."""
    return {
        "totalSteps": 8432,
        "totalKilocalories": 2150,
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
        "intensityMinutesGoal": 150,
        "vigorousIntensityMinutes": 22,
        "moderateIntensityMinutes": 45,
        "respirationAvg": 14.2,
        "avgSpo2": 97.1,
    }


@pytest.fixture
def sample_sleep():
    """Sample Garmin sleep data response."""
    return {
        "dailySleepDTO": {
            "sleepStartTimestampLocal": 1704067200,
            "sleepEndTimestampLocal": 1704094800,
            "sleepTimeSeconds": 25200,  # 7h
            "deepSleepSeconds": 5400,   # 1.5h
            "lightSleepSeconds": 12600,  # 3.5h
            "remSleepSeconds": 5400,    # 1.5h
            "awakeSleepSeconds": 1800,  # 30min
            "averageSpO2Value": 96.8,
            "averageRespirationValue": 13.8,
            "sleepScores": {"overall": {"value": 72}},
        }
    }


@pytest.fixture
def sample_hrv():
    """Sample HRV data."""
    return {
        "hrvSummary": {
            "lastNight": 48.5,
            "weeklyAvg": 46.2,
            "status": "BALANCED",
        },
        "hrvReadings": [
            {"hrvValue": 47, "readingTime": "2024-01-01T01:00:00.000"},
            {"hrvValue": 49, "readingTime": "2024-01-01T02:00:00.000"},
            {"hrvValue": 51, "readingTime": "2024-01-01T03:00:00.000"},
        ]
    }


@pytest.fixture
def sample_activity():
    """Sample Garmin activity JSON."""
    return {
        "activityId": 12345678901,
        "activityName": "Morning Run",
        "sportTypeId": 1,  # Running
        "activityType": {"typeKey": "running"},
        "startTimeLocal": "2024-01-15 07:30:00",
        "startTimeGMT": "2024-01-15 07:30:00",
        "duration": 3600.0,  # seconds
        "distance": 10000.0,  # meters
        "averageHR": 158,
        "maxHR": 178,
        "calories": 680,
        "averageSpeed": 2.78,  # m/s
        "activityTrainingLoad": 85.0,
        "aerobicTrainingEffect": 3.5,
        "anaerobicTrainingEffect": 1.2,
        "vo2MaxValue": 52.3,
        "averageRunningCadenceInStepsPerMinute": 172,
    }
