#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
"""Resolve the acting user id for a Garmin auth-server request.

Multi-tenant deployments send the app user id (from the authenticated session)
so the backend can scope tokens/sync per user. The addon (single-user) sends
nothing, so this returns ``None`` and callers fall back to shared/single-user
behavior.

Header takes precedence over the JSON body. A blank value is treated as absent.
Kept dependency-free (plain str/dict) so it is trivially unit-testable without
Flask.
"""

from typing import Any, Mapping, Optional

USER_ID_HEADER = "X-PulseCoach-User"
_BODY_KEY = "userId"


def resolve_user_id(
    header_value: Optional[str],
    body: Optional[Mapping[str, Any]],
) -> Optional[str]:
    """Return the trimmed user id from the header or JSON body, else ``None``."""
    candidates = [header_value]
    if body is not None:
        candidates.append(body.get(_BODY_KEY))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def demo() -> None:
    """Runnable self-check: ``python3 request_user.py``."""
    # Absent everywhere.
    assert resolve_user_id(None, None) is None
    assert resolve_user_id(None, {}) is None
    assert resolve_user_id("", {"userId": ""}) is None
    assert resolve_user_id("   ", {"userId": "  "}) is None

    # Header wins over body.
    assert resolve_user_id("hdr", {"userId": "body"}) == "hdr"

    # Body used when header absent/blank.
    assert resolve_user_id(None, {"userId": "body"}) == "body"
    assert resolve_user_id("  ", {"userId": "body"}) == "body"

    # Trimming.
    assert resolve_user_id("  u1 ", None) == "u1"

    # Non-string body values ignored.
    assert resolve_user_id(None, {"userId": 123}) is None

    print("request_user.py: all checks passed")


if __name__ == "__main__":
    demo()
