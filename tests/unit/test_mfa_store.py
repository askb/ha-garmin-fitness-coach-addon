# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Tests for mfa_store.MfaStore (per-user pending-MFA state)."""

import importlib.util
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "pulsecoach"
    / "rootfs"
    / "app"
    / "scripts"
    / "mfa_store.py"
)
_spec = importlib.util.spec_from_file_location("mfa_store", _SCRIPT)
assert _spec and _spec.loader
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_single_user_none_key_roundtrip():
    s = mod.MfaStore()
    assert s.get(None) is None
    assert not s.has(None)
    s.set(None, {"email": "a@x"})
    assert s.has(None)
    assert s.get(None) == {"email": "a@x"}
    s.clear(None)
    assert s.get(None) is None


def test_blank_ids_collapse_to_single_user_key():
    s = mod.MfaStore()
    s.set("   ", {"v": 1})
    assert s.get(None) == {"v": 1}
    assert s.get("") == {"v": 1}


def test_distinct_users_isolated():
    s = mod.MfaStore()
    s.set("alice", {"v": 1})
    s.set("bob", {"v": 2})
    assert s.get("alice") == {"v": 1}
    assert s.get("bob") == {"v": 2}
    s.clear("alice")
    assert s.get("alice") is None
    assert s.get("bob") == {"v": 2}


def test_whitespace_trimmed_consistently():
    s = mod.MfaStore()
    s.set(" carol ", {"v": 3})
    assert s.get("carol") == {"v": 3}
    assert s.has(" carol ")


def test_clear_missing_is_noop():
    s = mod.MfaStore()
    s.clear("nobody")  # must not raise


def test_sentinel_string_userid_does_not_collide_with_single_user():
    s = mod.MfaStore()
    s.set(None, {"slot": "single"})
    s.set("__single_user__", {"slot": "real"})
    # The single-user slot uses an object() sentinel, so a real user whose id
    # is literally "__single_user__" is isolated from it.
    assert s.get(None) == {"slot": "single"}
    assert s.get("__single_user__") == {"slot": "real"}


def test_demo_self_check_passes():
    mod.demo()
