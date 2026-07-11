#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
"""Stress Board interaction log helpers: add / list / delete quick-adds.

Shared by garmin-auth-server.py (the /auth/interactions endpoints behind the
in-app quick-add) and, indirectly, meeting-stress.py which consumes the same
JSONL file. stdlib only.

File shape (one JSON object per line, append-only friendly):
    {"person": str, "minutes": num, "end": ISO8601, "id": str, "logged_at": str}

Only person/minutes/end matter to meeting-stress.py; id/logged_at are UI
bookkeeping. Lines written by hand (HA shell_command) have no id — they get a
stable content-hash id so the UI can still list and delete them. Malformed
lines are never touched: the log stays forgiving for manual writers.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

INTERACTIONS_PATH = "/share/pulsecoach/interactions.jsonl"

MAX_PERSON_LEN = 200
MAX_MINUTES = 1440  # one day
DEFAULT_LIST_LIMIT = 20

# Serialises UI-driven writes (append vs delete-rewrite) within the auth
# server process. HA shell_command appends from other processes are not
# covered, but those are single O_APPEND writes — only the UI rewrites.
_WRITE_LOCK = threading.Lock()


class InteractionError(ValueError):
    """Invalid interaction input (message is user-safe)."""


def _line_id(rec: dict, raw: str) -> str:
    """Stable id for a line: the stored id, else a content hash.

    sha256 rather than sha1 purely to keep linters quiet — the id is a
    UI handle for list/delete, not a security boundary.
    """
    stored = rec.get("id")
    if isinstance(stored, str) and stored:
        return stored
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _parse_line(raw: str) -> dict | None:
    """Return a valid interaction record from a raw line, else None.

    Mirrors meeting-stress.py load_interactions(): person/minutes/end must
    parse, everything else is forgiven.
    """
    try:
        rec = json.loads(raw)
        person = str(rec["person"]).strip()
        minutes = float(rec.get("minutes", 30))
        end = datetime.fromisoformat(str(rec["end"]).replace("Z", "+00:00"))
    except (KeyError, ValueError, TypeError):
        return None
    # json.loads accepts NaN/Infinity literals; a non-finite value would
    # blow up the int() normalisation below and poison every listing.
    if not person or not math.isfinite(minutes) or minutes <= 0:
        return None
    # meeting-stress.py parse_ts() scores naive timestamps as UTC — mirror
    # that here so hand-written lines list consistently with how they score.
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return {
        "id": _line_id(rec, raw),
        "person": person,
        "minutes": int(minutes) if minutes == int(minutes) else minutes,
        "end": end.isoformat(),
    }


def add_interaction(person: str, minutes: object,
                    end: str | None = None) -> dict:
    """Validate and append one interaction; returns the stored record.

    end defaults to now (UTC). Raises InteractionError on bad input so the
    HTTP layer can 400 with the message verbatim.
    """
    person = str(person or "").strip()
    if not person or len(person) > MAX_PERSON_LEN:
        raise InteractionError(
            f"person must be 1-{MAX_PERSON_LEN} characters")
    try:
        mins = float(minutes)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise InteractionError("minutes must be a number") from None
    if not 0 < mins <= MAX_MINUTES:
        raise InteractionError(f"minutes must be 1-{MAX_MINUTES}")
    now = datetime.now(timezone.utc)
    if end is None:
        end_dt = now
    else:
        try:
            end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        except ValueError:
            raise InteractionError(
                "end must be an ISO 8601 timestamp") from None
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        if end_dt > now + timedelta(days=1):
            raise InteractionError("end is in the future")
    rec = {
        "person": person,
        "minutes": int(mins) if mins == int(mins) else mins,
        "end": end_dt.isoformat(),
        "id": uuid.uuid4().hex[:12],
        "logged_at": now.isoformat(),
    }
    os.makedirs(os.path.dirname(INTERACTIONS_PATH), exist_ok=True)
    with _WRITE_LOCK, open(INTERACTIONS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return {k: rec[k] for k in ("id", "person", "minutes", "end")}


def list_interactions(limit: int = DEFAULT_LIST_LIMIT) -> list[dict]:
    """Newest-first valid interactions, capped at `limit` (<=0 == none)."""
    if int(limit) <= 0:
        return []
    try:
        with open(INTERACTIONS_PATH, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    entries = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        rec = _parse_line(raw)
        if rec is not None:
            entries.append(rec)
    entries.reverse()  # file is append-only, so reversed == newest first
    return entries[:int(limit)]


def delete_interaction(iid: str) -> bool:
    """Remove the first line whose id matches; True when something went.

    Malformed lines (hand-written notes) are preserved verbatim. The rewrite
    is atomic (tmp + rename) so a crash can't truncate the log, and holds
    _WRITE_LOCK for the whole read→rewrite so a concurrent UI add can't be
    lost to the rename.
    """
    with _WRITE_LOCK:
        try:
            with open(INTERACTIONS_PATH, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return False
        kept: list[str] = []
        removed = False
        for raw in lines:
            stripped = raw.strip()
            if not removed and stripped:
                try:
                    rec = json.loads(stripped)
                except ValueError:
                    rec = None
                if isinstance(rec, dict) and _line_id(rec, stripped) == iid:
                    removed = True
                    continue
            kept.append(raw)
        if not removed:
            return False
        tmp = INTERACTIONS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(kept)
        os.replace(tmp, INTERACTIONS_PATH)
        return True
