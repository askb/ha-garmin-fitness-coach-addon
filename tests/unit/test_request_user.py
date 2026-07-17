# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Tests for request_user.resolve_user_id."""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "pulsecoach"
    / "rootfs"
    / "app"
    / "scripts"
    / "request_user.py"
)
_spec = importlib.util.spec_from_file_location("request_user", _SCRIPT)
assert _spec and _spec.loader
ru = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ru)


@pytest.mark.parametrize(
    "header,body",
    [
        (None, None),
        (None, {}),
        ("", {"userId": ""}),
        ("   ", {"userId": "  "}),
        (None, {"userId": 123}),  # non-string ignored
        (None, {"userId": None}),
    ],
)
def test_absent_returns_none(header, body):
    assert ru.resolve_user_id(header, body) is None


def test_header_takes_precedence():
    assert ru.resolve_user_id("hdr", {"userId": "body"}) == "hdr"


def test_body_used_when_header_blank():
    assert ru.resolve_user_id("  ", {"userId": "body"}) == "body"
    assert ru.resolve_user_id(None, {"userId": "body"}) == "body"


def test_trimming():
    assert ru.resolve_user_id("  u1 ", None) == "u1"
    assert ru.resolve_user_id(None, {"userId": "  u2 "}) == "u2"


def test_demo_self_check_passes():
    ru.demo()
