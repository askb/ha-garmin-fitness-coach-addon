#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Smoke eval for the PulseCoach workout recommendation engine.

Runs realistic end-to-end scenarios against recommend_workout() and
verifies cross-cutting invariants that unit tests do not cover.

Usage:
    python3 evals/smoke_eval.py

Exits 0 when every scenario passes; prints failures and exits 1 otherwise.
"""

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HA_NOTIFY_PATH = _REPO_ROOT / "pulsecoach" / "rootfs" / "app" / "scripts" / "ha-notify.py"


def load_engine() -> ModuleType:
    """Load ha-notify.py with mocked deps, mirroring tests/test_coaching_engine.py.

    Stubs psycopg2 when it is not installed so the eval stays standalone on
    machines without PostgreSQL client libraries (ha-notify.py exits at import
    time if psycopg2 is missing).
    """
    if "psycopg2" not in sys.modules:
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            psycopg2_stub = MagicMock()
            sys.modules["psycopg2"] = psycopg2_stub
            sys.modules["psycopg2.extras"] = psycopg2_stub.extras

    with patch.dict(
        "os.environ",
        {
            "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
            "SUPERVISOR_TOKEN": "test-token",
        },
    ):
        mod_name = "ha-notify"
        sys.modules.pop(mod_name, None)
        spec = importlib.util.spec_from_file_location(mod_name, str(_HA_NOTIFY_PATH))
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load ha-notify from {_HA_NOTIFY_PATH}")
        mod: ModuleType = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return mod


@dataclass(frozen=True)
class Scenario:
    """One realistic input plus the invariants its output must satisfy."""

    name: str
    signals: dict[str, Any]
    checks: tuple[Callable[[dict], str | None], ...] = field(default_factory=tuple)


def _rest_has_rationale(result: dict) -> str | None:
    if result.get("is_rest_day") and not result.get("rationale"):
        return "rest day recommended without a rationale"
    return None


def _no_hard_workout(result: dict) -> str | None:
    intensity = str(result.get("intensity", "")).lower()
    if not result.get("is_rest_day") and intensity in {"high", "hard", "max"}:
        return f"high-intensity workout despite critical signals: {result}"
    return None


def _must_rest(result: dict) -> str | None:
    if not result.get("is_rest_day"):
        return f"expected rest day, got: {result}"
    return None


def _must_train(result: dict) -> str | None:
    if result.get("is_rest_day"):
        return f"expected a workout, got rest: {result.get('rationale')}"
    return None


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="fresh athlete, balanced load",
        signals=dict(
            acwr=1.0, tsb=5.0, body_battery=80, stress_score=25,
            sleep_debt_minutes=15, consecutive_hard_days=0,
            readiness_score=85, garmin_training_status="PRODUCTIVE",
        ),
        checks=(_must_train, _rest_has_rationale),
    ),
    Scenario(
        name="overreached: high ACWR + deep negative TSB",
        signals=dict(
            acwr=1.7, tsb=-30.0, body_battery=25, stress_score=70,
            sleep_debt_minutes=150, consecutive_hard_days=4,
            readiness_score=18, garmin_training_status="OVERREACHING",
        ),
        checks=(_must_rest, _rest_has_rationale),
    ),
    Scenario(
        name="critically low readiness alone",
        signals=dict(
            acwr=1.0, tsb=0.0, body_battery=60, stress_score=40,
            sleep_debt_minutes=30, consecutive_hard_days=1,
            readiness_score=20, garmin_training_status=None,
        ),
        checks=(_must_rest, _rest_has_rationale),
    ),
    Scenario(
        name="all signals missing degrades conservatively",
        signals=dict(
            acwr=None, tsb=None, body_battery=None, stress_score=None,
            sleep_debt_minutes=None, consecutive_hard_days=0,
            readiness_score=None, garmin_training_status=None,
        ),
        checks=(_no_hard_workout, _rest_has_rationale),
    ),
    Scenario(
        name="sleep-deprived but otherwise fine",
        signals=dict(
            acwr=1.1, tsb=-5.0, body_battery=45, stress_score=55,
            sleep_debt_minutes=180, consecutive_hard_days=1,
            readiness_score=45, garmin_training_status="MAINTAINING",
        ),
        checks=(_no_hard_workout, _rest_has_rationale),
    ),
)


def run() -> int:
    """Execute every scenario; return the number of failures."""
    engine = load_engine()
    failures: list[str] = []

    for scenario in SCENARIOS:
        result = engine.recommend_workout(**scenario.signals)
        if not isinstance(result, dict):
            failures.append(f"{scenario.name}: non-dict result {result!r}")
            continue
        for check in scenario.checks:
            problem = check(result)
            if problem:
                failures.append(f"{scenario.name}: {problem}")

    for failure in failures:
        print(f"FAIL {failure}")
    print(f"{len(SCENARIOS) - len(failures)}/{len(SCENARIOS)} scenarios passed")
    return len(failures)


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
