# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/collect_failures.py.

Covers each log parser, the signature stability invariant, and the
dedup/cap behaviour of the main entry point. These guard against silent
regressions that would stop self-healing CI from opening issues.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "collect_failures.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import collect_failures as cf  # noqa: E402


def test_parse_pytest_single_failure() -> None:
    text = (
        "tests/test_x.py::test_one PASSED\n"
        "tests/test_x.py::test_two FAILED\n"
        "FAILED tests/test_x.py::test_two - AssertionError: nope\n"
        "1 failed, 1 passed\n"
    )
    out = cf.parse_pytest(text)
    assert len(out) == 1
    assert out[0]["component"] == "pytest"
    assert "test_two" in out[0]["key"]
    assert len(out[0]["signature"]) == 12


def test_parse_pytest_multiple_failures_unique_signatures() -> None:
    text = (
        "FAILED tests/test_a.py::test_one - boom\n"
        "FAILED tests/test_b.py::test_two - bam\n"
    )
    out = cf.parse_pytest(text)
    assert len(out) == 2
    assert out[0]["signature"] != out[1]["signature"]


def test_parse_precommit_hook_failure() -> None:
    text = (
        "yamllint.................................................................Failed\n"
        "shellcheck...............................................................Passed\n"
        "ruff.....................................................................Error\n"
    )
    out = cf.parse_precommit(text)
    components = {o["key"] for o in out}
    assert "yamllint" in components
    assert "ruff" in components
    assert all(o["component"] == "pre-commit" for o in out)


def test_parse_hadolint_json() -> None:
    text = json.dumps(
        [
            {
                "code": "DL3008",
                "message": "Pin versions in apt-get install",
                "file": "Dockerfile",
                "line": 5,
            }
        ]
    )
    out = cf.parse_hadolint(text)
    assert len(out) == 1
    assert out[0]["component"] == "hadolint"
    assert "DL3008" in out[0]["title"]


def test_parse_hadolint_invalid_json_returns_empty() -> None:
    assert cf.parse_hadolint("not json") == []
    assert cf.parse_hadolint('{"not": "list"}') == []


def test_parse_tsc_error() -> None:
    text = "packages/api/src/router/coach.ts(466,12): error TS2345: nope\n"
    out = cf.parse_tsc(text)
    assert len(out) == 1
    assert out[0]["component"] == "tsc"
    assert "TS2345" in out[0]["title"]


def test_parse_eslint_error() -> None:
    text = (
        "/repo/src/foo.ts\n"
        "  12:34  error  Unexpected any  @typescript-eslint/no-explicit-any\n"
        "/repo/src/bar.ts\n"
        "  5:1   error  Missing return type  @typescript-eslint/explicit-function-return-type\n"
    )
    out = cf.parse_eslint(text)
    assert len(out) == 2
    assert all(o["component"] == "eslint" for o in out)


def test_signature_is_stable() -> None:
    # The signature must be deterministic so the dedup logic in triage
    # actually deduplicates across scan runs.
    s1 = cf.sig("pytest", "tests/foo::bar")
    s2 = cf.sig("pytest", "tests/foo::bar")
    assert s1 == s2
    assert len(s1) == 12


def test_main_dedupes_by_signature(tmp_path: Path) -> None:
    log = tmp_path / "pytest.log"
    log.write_text(
        "FAILED tests/x.py::test_one - boom\n"
        "FAILED tests/x.py::test_one - boom again\n"
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), f"pytest={log}"],
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(result.stdout)
    assert len(out) == 1


def test_main_caps_at_max_failures(tmp_path: Path) -> None:
    log = tmp_path / "pytest.log"
    log.write_text(
        "\n".join(
            f"FAILED tests/test_{i}.py::test_case - err" for i in range(20)
        )
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), f"pytest={log}"],
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(result.stdout)
    assert len(out) == cf.MAX_FAILURES


def test_main_missing_file_returns_empty(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), f"pytest={tmp_path / 'nope.log'}"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == []


def test_main_no_args_returns_empty() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == []


def test_main_mixed_sources(tmp_path: Path) -> None:
    pytest_log = tmp_path / "pytest.log"
    pytest_log.write_text("FAILED tests/x.py::test_a - boom\n")
    precommit_log = tmp_path / "precommit.log"
    precommit_log.write_text(
        "yamllint.................................Failed\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            f"pytest={pytest_log}",
            f"precommit={precommit_log}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(result.stdout)
    components = {f["component"] for f in out}
    assert components == {"pytest", "pre-commit"}


@pytest.mark.parametrize(
    "log_text",
    [
        "",
        "all green\n" * 20,
        "ERROR but not a recognised pattern\n",
    ],
)
def test_parsers_handle_clean_output(log_text: str) -> None:
    assert cf.parse_pytest(log_text) == []
    assert cf.parse_precommit(log_text) == []
    assert cf.parse_tsc(log_text) == []
