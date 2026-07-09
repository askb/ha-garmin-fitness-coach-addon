#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
"""Google Calendar helpers for PulseCoach: linking, calendar list, event fetch.

Shared by garmin-auth-server.py (link/unlink/list-calendars HTTP endpoints)
and meeting-stress.py (event fetch). stdlib only (urllib) — no google-auth
dependency for a read-only refresh-token flow.

Token file shape (written by generate-gcal-token.py or the in-UI link):
    {"client_id": str, "client_secret": str, "refresh_token": str}

Calendar selection (which calendars feed the Stress Board) lives separately in
gcal-calendars.json as a JSON list of calendar ids; absent == ["primary"], so
existing single-calendar installs keep working with no migration.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

TOKEN_PATH = "/data/gcal-token.json"
# World-readable drop location: users without /data access copy a token here
# (Samba/SSH addon) and it is adopted into /data on first read.
DROP_PATH = "/share/pulsecoach/gcal-token.json"
CALENDARS_PATH = "/data/gcal-calendars.json"

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/calendar/v3"


class GcalError(RuntimeError):
    """Any Google Calendar linking / API failure (message is user-safe)."""


# --------------------------------------------------------------------------- #
# Token adoption + presence
# --------------------------------------------------------------------------- #
def adopt_dropped_token() -> None:
    """Move a user-dropped token from /share (world-readable) into /data.

    Dropping a fresh token in /share IS the refresh mechanism for users with
    no direct /data access, so an overwrite is deliberate — anything that can
    write /share already controls calendar input wholesale.

    Best-effort: a symlinked drop is refused (never adopted into /data), and
    any filesystem error is logged rather than raised so callers like
    ``linked()`` can't be crashed by a bad /share drop.
    """
    if not (os.path.exists(DROP_PATH) and os.path.isdir("/data")):
        return
    if (os.path.islink(DROP_PATH)
            or os.path.islink(os.path.dirname(DROP_PATH))
            or not os.path.isfile(DROP_PATH)):
        print("Refusing to adopt gcal-token.json: /share drop is not a regular file")
        return
    import shutil

    try:
        shutil.move(DROP_PATH, TOKEN_PATH)
        os.chmod(TOKEN_PATH, 0o600)
        print("Adopted gcal-token.json from /share into /data")
    except OSError as exc:
        print(f"Could not adopt gcal-token.json from /share: {exc}")


def linked() -> bool:
    """True when a Google Calendar refresh token is available."""
    adopt_dropped_token()
    # A symlink is refused by load_token()'s O_NOFOLLOW, so don't report it as
    # linked — otherwise the UI says "linked" but every operation fails.
    return os.path.isfile(TOKEN_PATH) and not os.path.islink(TOKEN_PATH)


def load_token() -> dict:
    """Load the stored token dict, adopting a /share drop first.

    Opens with O_NOFOLLOW so a symlink planted at TOKEN_PATH can't redirect
    the read, mirroring the write hardening in ``_secure_write_json``.
    """
    adopt_dropped_token()
    try:
        fd = os.open(TOKEN_PATH, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as f:
            return json.load(f)
    except FileNotFoundError as exc:
        raise GcalError("no Google Calendar token is linked") from exc
    except (OSError, ValueError) as exc:
        raise GcalError(f"stored Google Calendar token is unreadable ({exc})") from exc


# --------------------------------------------------------------------------- #
# Secure writes (mirror garmin-auth-server import-tokens hardening)
# --------------------------------------------------------------------------- #
def _secure_write_json(path: str, payload: object) -> None:
    """Write JSON owner-only, refusing to follow a pre-planted symlink.

    O_NOFOLLOW so an attacker cannot redirect the write via a symlink at
    ``path``; 0o600 so the credential file is never group/world readable.
    """
    parent = os.path.dirname(path)
    try:
        if parent:
            os.makedirs(parent, mode=0o700, exist_ok=True)
            if os.path.islink(parent):
                raise GcalError("target directory is a symlink; refusing to write")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        # fchmod on the open fd (not chmod on the path) so an existing file's
        # perms are tightened without a TOCTOU window on the name.
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
    except OSError as exc:
        raise GcalError(f"could not write {os.path.basename(path)} ({exc})") from exc


# --------------------------------------------------------------------------- #
# OAuth refresh
# --------------------------------------------------------------------------- #
def _refresh_access_token(tok: dict) -> str:
    """Exchange a stored refresh token for a short-lived access token."""
    for key in ("client_id", "client_secret", "refresh_token"):
        if not tok.get(key):
            raise GcalError(f"token is missing {key}")
    body = urllib.parse.urlencode({
        "client_id": tok["client_id"],
        "client_secret": tok["client_secret"],
        "refresh_token": tok["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        # Google returns 400/401 with a JSON {error, error_description} body
        # for bad creds — surface the reason so the UI can explain the failure.
        detail = ""
        try:
            payload = json.loads(exc.read().decode() or "{}")
            detail = payload.get("error_description") or payload.get("error") or ""
        except (ValueError, OSError):
            pass
        suffix = f": {detail}" if detail else ""
        raise GcalError(f"token refresh failed (HTTP {exc.code}){suffix}") from exc
    except ValueError as exc:
        raise GcalError("token refresh returned a non-JSON response") from exc
    except OSError as exc:
        raise GcalError(f"could not reach Google ({exc})") from exc
    access = data.get("access_token")
    if not access:
        # Don't echo the payload — it may carry sensitive fields.
        raise GcalError(f"token refresh failed ({data.get('error', 'unknown_error')})")
    return access


def validate_token(client_id: str, client_secret: str, refresh_token: str) -> None:
    """Raise GcalError unless these credentials can obtain an access token."""
    _refresh_access_token({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    })


def save_token(client_id: str, client_secret: str, refresh_token: str) -> None:
    """Persist token credentials to /data (owner-only).

    Callers are responsible for validating the token first (see
    ``validate_token``); this helper only writes the file.
    """
    _secure_write_json(TOKEN_PATH, {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    })
    # Drop any stale /share token so a later adopt_dropped_token() can't move
    # it over the credentials we just linked via the UI. A missing drop is the
    # normal case; any other failure means the stale token could still win, so
    # surface it rather than silently reverting later.
    try:
        os.remove(DROP_PATH)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise GcalError(
            f"linked token, but could not remove the stale /share drop ({exc}); "
            "delete /share/pulsecoach/gcal-token.json manually"
        ) from exc


def unlink() -> None:
    """Remove the token, the calendar selection, and any pending /share drop."""
    for path in (TOKEN_PATH, CALENDARS_PATH, DROP_PATH):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


# --------------------------------------------------------------------------- #
# Calendar selection
# --------------------------------------------------------------------------- #
def _norm_ids(ids: list) -> list[str]:
    """Keep whitespace-stripped, unique string ids; ignore non-strings/blanks."""
    out: list[str] = []
    for x in ids:
        if not isinstance(x, str):
            continue
        s = x.strip()
        if s and s not in out:
            out.append(s)
    return out


def selected_calendar_ids() -> list[str]:
    """Calendar ids feeding the Stress Board; absent selection == ["primary"].

    "primary" is the Calendar API alias for the account's default calendar, so
    the default keeps pre-multi-calendar installs behaving exactly as before.
    """
    try:
        fd = os.open(CALENDARS_PATH, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as f:
            ids = json.load(f)
        if isinstance(ids, list):
            cleaned = _norm_ids(ids)
            if cleaned:
                return cleaned
    except (OSError, ValueError):
        pass
    return ["primary"]


def save_selected(ids: list[str]) -> None:
    """Persist the chosen calendar ids (empty list falls back to primary)."""
    _secure_write_json(CALENDARS_PATH, _norm_ids(ids) or ["primary"])


# --------------------------------------------------------------------------- #
# Calendar API
# --------------------------------------------------------------------------- #
def _api_get(url: str, access: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        # Surface Google's JSON error message (e.g. insufficient scope) so the
        # failure is actionable rather than a bare status code.
        detail = ""
        try:
            payload = json.loads(exc.read().decode() or "{}")
            err = payload.get("error")
            if isinstance(err, dict):
                detail = err.get("message", "")
            elif isinstance(err, str):
                detail = payload.get("error_description") or err
        except (ValueError, OSError):
            pass
        suffix = f": {detail}" if detail else ""
        raise GcalError(f"Calendar API error (HTTP {exc.code}){suffix}") from exc
    except ValueError as exc:
        raise GcalError("Calendar API returned a non-JSON response") from exc
    except OSError as exc:
        raise GcalError(f"could not reach Google ({exc})") from exc
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        raise GcalError(f"Calendar API error {err.get('code')}: {err.get('message')}")
    return data


def list_calendars() -> list[dict]:
    """Return the account's calendars with a ``selected`` flag for the UI.

    Selection precedence: an explicit saved selection wins; with no saved
    selection yet, only the primary calendar is pre-checked (today's default).
    """
    access = _refresh_access_token(load_token())
    items = _api_get(f"{API_BASE}/users/me/calendarList", access).get("items", [])
    has_selection = os.path.exists(CALENDARS_PATH)
    saved = set(selected_calendar_ids())
    out: list[dict] = []
    for it in items:
        cid = it.get("id")
        if not cid:
            continue
        primary = bool(it.get("primary"))
        # A saved selection may store the "primary" alias rather than the real
        # primary calendar's id (the account email), so honour either form.
        selected = (
            (cid in saved or (primary and "primary" in saved))
            if has_selection
            else primary
        )
        out.append({
            "id": cid,
            "summary": it.get("summaryOverride") or it.get("summary") or cid,
            "primary": primary,
            "selected": selected,
        })
    return out


def _item_to_event(item: dict) -> dict | None:
    """Map one Calendar API item to our event schema; None if unusable."""
    start = item.get("start", {}).get("dateTime")
    end = item.get("end", {}).get("dateTime")
    if not start or not end:
        return None  # all-day event
    attendees = []
    for att in item.get("attendees", []):
        if (att.get("responseStatus") == "declined"
                or att.get("resource") or att.get("self")):
            continue
        name = att.get("displayName") or att.get("email", "").split("@")[0]
        if name:
            attendees.append(name)
    if not attendees:
        return None
    return {
        "start": start,
        "end": end,
        "title": item.get("summary", "(untitled)"),
        "attendees": sorted(set(attendees)),
    }


def _list_events_for_calendar(access: str, calendar_id: str, days: int) -> list[dict]:
    """Raw Calendar API items for one calendar over the last `days`."""
    now = datetime.now(timezone.utc)
    base_params = {
        "timeMin": (now - timedelta(days=days)).isoformat(),
        "timeMax": now.isoformat(),
        "singleEvents": "true",   # expand recurrences
        "orderBy": "startTime",
        "maxResults": "250",
    }
    url = f"{API_BASE}/calendars/{urllib.parse.quote(calendar_id, safe='')}/events"
    items: list[dict] = []
    page_token = ""
    while True:
        params = dict(base_params)
        if page_token:
            params["pageToken"] = page_token
        data = _api_get(f"{url}?{urllib.parse.urlencode(params)}", access)
        items.extend(data.get("items", []))
        page_token = data.get("nextPageToken", "")
        if not page_token:
            break
    return items


def _dedup_key(item: dict, ev: dict) -> str:
    """Stable identity for cross-calendar de-duplication.

    Recurring instances expanded via ``singleEvents=true`` share a single
    ``iCalUID`` across every occurrence, so the start time is part of the key —
    otherwise distinct occurrences of a series would collapse into one meeting.
    """
    uid = item.get("iCalUID") or item.get("id") or ev["title"]
    return f"{uid}|{ev['start']}"


def fetch_events(days: int) -> list[dict]:
    """Pull the last `days` of events across every selected calendar.

    Events shared across calendars carry the same ``iCalUID`` and start; we
    keep the first scorable copy so a meeting on both your calendar and a team
    calendar isn't double-counted.
    """
    access = _refresh_access_token(load_token())
    calendar_ids = selected_calendar_ids()
    seen: set[str] = set()
    events: list[dict] = []
    for cid in calendar_ids:
        for item in _list_events_for_calendar(access, cid, days):
            ev = _item_to_event(item)
            if ev is None:
                continue
            key = _dedup_key(item, ev)
            if key in seen:
                continue
            seen.add(key)
            events.append(ev)
    print(f"Fetched {len(events)} meetings from {len(calendar_ids)} "
          f"calendar(s) (last {days}d)")
    return events


# --------------------------------------------------------------------------- #
# Offline self-check: dedup + mapping (no network). Run: python3 gcal.py
# --------------------------------------------------------------------------- #
def _selfcheck() -> None:
    # _item_to_event drops all-day / declined-only / self-only events.
    assert _item_to_event({"start": {"date": "2026-01-01"},
                           "end": {"date": "2026-01-02"}}) is None
    assert _item_to_event({
        "start": {"dateTime": "2026-01-01T10:00:00Z"},
        "end": {"dateTime": "2026-01-01T11:00:00Z"},
        "attendees": [{"self": True}],
    }) is None
    ev = _item_to_event({
        "start": {"dateTime": "2026-01-01T10:00:00Z"},
        "end": {"dateTime": "2026-01-01T11:00:00Z"},
        "summary": "1:1",
        "attendees": [
            {"displayName": "Bob"},
            {"email": "declined@x.com", "responseStatus": "declined"},
            {"displayName": "Room 5", "resource": True},
        ],
    })
    assert ev == {
        "start": "2026-01-01T10:00:00Z",
        "end": "2026-01-01T11:00:00Z",
        "title": "1:1",
        "attendees": ["Bob"],
    }, ev

    # Dedup across calendars using the SAME key as fetch_events (_dedup_key):
    # iCalUID + start, so recurring occurrences stay distinct.
    def dedup(items: list[dict]) -> list[dict]:
        seen: set[str] = set()
        out: list[dict] = []
        for it in items:
            e = _item_to_event(it)
            if e is None:
                continue
            key = _dedup_key(it, e)
            if key in seen:
                continue
            seen.add(key)
            out.append(e)
        return out

    shared = {
        "iCalUID": "dup@google.com",
        "start": {"dateTime": "2026-01-02T09:00:00Z"},
        "end": {"dateTime": "2026-01-02T09:30:00Z"},
        "summary": "standup",
        "attendees": [{"displayName": "Ada"}],
    }
    other = {
        "iCalUID": "solo@google.com",
        "start": {"dateTime": "2026-01-02T14:00:00Z"},
        "end": {"dateTime": "2026-01-02T15:00:00Z"},
        "summary": "review",
        "attendees": [{"displayName": "Cyd"}],
    }
    merged = dedup([shared, dict(shared), other])  # same meeting twice + one unique
    assert len(merged) == 2, merged
    assert {e["title"] for e in merged} == {"standup", "review"}, merged

    # Recurring series: two occurrences share iCalUID but differ by start —
    # they must NOT collapse into one.
    tomorrow = dict(shared)
    tomorrow["start"] = {"dateTime": "2026-01-03T09:00:00Z"}
    tomorrow["end"] = {"dateTime": "2026-01-03T09:30:00Z"}
    recurring = dedup([shared, tomorrow])
    assert len(recurring) == 2, recurring

    # selected_calendar_ids default is ["primary"] when unset.
    global CALENDARS_PATH
    saved = CALENDARS_PATH
    CALENDARS_PATH = "/nonexistent/gcal-calendars.json"
    try:
        assert selected_calendar_ids() == ["primary"]
    finally:
        CALENDARS_PATH = saved
    print("gcal.py self-check OK")


if __name__ == "__main__":
    _selfcheck()
