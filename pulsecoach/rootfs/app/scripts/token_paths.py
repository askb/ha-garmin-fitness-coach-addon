#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
"""Resolve the Garmin token directory for a given user.

Foundation for multi-tenant token storage (Phase 2). The addon is single-user:
when no user id is supplied the shared base directory is returned unchanged, so
existing behavior is preserved. When a user id is supplied (hosted/standalone
deployment) tokens live under a per-user subdirectory.

Security: the user id is **hashed** (never interpolated raw) so an
attacker-controlled id cannot escape the base directory via path traversal
(the hash output is fixed-length lowercase hex).
"""

import hashlib
import os

_USERS_SUBDIR = "users"


def user_token_dir(base_dir: str, user_id: str | None) -> str:
    """Return the token directory for ``user_id`` under ``base_dir``.

    - Falsy/blank ``user_id`` → ``base_dir`` unchanged (single-user/addon mode).
    - Otherwise → ``base_dir/users/<sha256(user_id)>``. The id is hashed so the
      result is always contained within ``base_dir`` regardless of the id's
      contents (no ``..`` / separators can survive hashing).
    """
    if user_id is None or not user_id.strip():
        return base_dir
    digest = hashlib.sha256(user_id.strip().encode("utf-8")).hexdigest()
    return os.path.join(base_dir, _USERS_SUBDIR, digest)


def demo() -> None:
    """Runnable self-check: ``python3 token_paths.py``."""
    base = "/data/garmin-tokens"

    # Single-user / addon mode: unchanged.
    assert user_token_dir(base, None) == base
    assert user_token_dir(base, "") == base
    assert user_token_dir(base, "   ") == base

    # Per-user mode: stable, hex-only leaf, contained within base.
    d = user_token_dir(base, "seed-user-001")
    assert d == user_token_dir(base, "seed-user-001"), "must be deterministic"
    assert d.startswith(base + os.sep + _USERS_SUBDIR + os.sep)
    leaf = os.path.basename(d)
    assert len(leaf) == 64 and all(c in "0123456789abcdef" for c in leaf)

    # Distinct users → distinct dirs.
    assert user_token_dir(base, "a") != user_token_dir(base, "b")

    # Traversal attempts cannot escape base_dir (id is hashed).
    for evil in ["../../etc/shadow", "..", "a/../../b", "\x00/etc"]:
        got = user_token_dir(base, evil)
        assert os.path.commonpath([base, got]) == base, evil
        assert ".." not in got

    print("token_paths.py: all checks passed")


if __name__ == "__main__":
    demo()
