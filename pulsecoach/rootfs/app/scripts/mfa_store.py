#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
"""Per-user pending-MFA state for the Garmin auth server.

The addon was single-user and held MFA state in one module-global dict, so two
users mid-login would clobber each other. This keyed store isolates pending MFA
state per user while preserving single-user behavior: when no user id is given
all operations share one sentinel key (identical to the old global).

Holds only transient in-memory state (email/password/client during the brief
MFA window). Nothing is persisted to disk.
"""

from typing import Any, Optional

# Unique sentinel for the single-user (addon) slot. Using an object() — not a
# string — means no real user_id (always a str) can ever collide with it.
_SINGLE_USER_KEY = object()


def _key(user_id: Optional[str]) -> object:
    if user_id is None or not user_id.strip():
        return _SINGLE_USER_KEY
    return user_id.strip()


class MfaStore:
    """In-memory per-user pending-MFA state."""

    def __init__(self) -> None:
        self._by_user: dict[Any, dict[str, Any]] = {}

    def set(self, user_id: Optional[str], state: dict[str, Any]) -> None:
        self._by_user[_key(user_id)] = state

    def get(self, user_id: Optional[str]) -> Optional[dict[str, Any]]:
        return self._by_user.get(_key(user_id))

    def clear(self, user_id: Optional[str]) -> None:
        self._by_user.pop(_key(user_id), None)

    def has(self, user_id: Optional[str]) -> bool:
        return _key(user_id) in self._by_user


def demo() -> None:
    """Runnable self-check: ``python3 mfa_store.py``."""
    s = MfaStore()

    # Single-user (None) behaves like the old global.
    assert s.get(None) is None
    s.set(None, {"email": "a@x"})
    assert s.get(None) == {"email": "a@x"}
    assert s.has(None)
    s.clear(None)
    assert not s.has(None)

    # Blank ids collapse to the single-user key.
    s.set("  ", {"email": "blank"})
    assert s.get(None) == {"email": "blank"}
    s.clear(None)

    # Distinct users are isolated; one clear doesn't affect the other.
    s.set("alice", {"pw": 1})
    s.set("bob", {"pw": 2})
    assert s.get("alice") == {"pw": 1}
    assert s.get("bob") == {"pw": 2}
    s.clear("alice")
    assert s.get("alice") is None
    assert s.get("bob") == {"pw": 2}

    # Whitespace is trimmed consistently.
    s.set(" carol ", {"pw": 3})
    assert s.get("carol") == {"pw": 3}

    # A user id equal to the old sentinel string must NOT collide with the
    # single-user slot (the sentinel is now an object(), not "__single_user__").
    s2 = MfaStore()
    s2.set(None, {"slot": "single"})
    s2.set("__single_user__", {"slot": "real-user"})
    assert s2.get(None) == {"slot": "single"}
    assert s2.get("__single_user__") == {"slot": "real-user"}

    print("mfa_store.py: all checks passed")


if __name__ == "__main__":
    demo()
