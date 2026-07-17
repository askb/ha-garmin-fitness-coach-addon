# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Tests for token_paths.user_token_dir (per-user Garmin token directory)."""

import importlib.util
import os
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "pulsecoach"
    / "rootfs"
    / "app"
    / "scripts"
    / "token_paths.py"
)
_spec = importlib.util.spec_from_file_location("token_paths", _SCRIPT)
assert _spec and _spec.loader
tp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tp)

BASE = "/data/garmin-tokens"


@pytest.mark.parametrize("blank", [None, "", "   ", "\t"])
def test_blank_user_returns_base_unchanged(blank):
    assert tp.user_token_dir(BASE, blank) == BASE


def test_per_user_dir_is_deterministic_and_hex():
    a = tp.user_token_dir(BASE, "seed-user-001")
    b = tp.user_token_dir(BASE, "seed-user-001")
    assert a == b
    leaf = os.path.basename(a)
    assert len(leaf) == 64
    assert all(c in "0123456789abcdef" for c in leaf)


def test_distinct_users_get_distinct_dirs():
    assert tp.user_token_dir(BASE, "alice") != tp.user_token_dir(BASE, "bob")


def test_whitespace_is_trimmed_consistently():
    assert tp.user_token_dir(BASE, "  alice ") == tp.user_token_dir(BASE, "alice")


@pytest.mark.parametrize(
    "evil",
    ["../../etc/shadow", "..", "a/../../b", "/etc/passwd", "\x00/etc", "a/b/c"],
)
def test_traversal_ids_cannot_escape_base(evil):
    got = tp.user_token_dir(BASE, evil)
    assert os.path.commonpath([BASE, got]) == BASE
    assert ".." not in got
    # Leaf is always the fixed-length hash, never the raw id.
    assert len(os.path.basename(got)) == 64


def test_demo_self_check_passes():
    tp.demo()
