#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Garmin Connect authentication microservice for PulseCoach HA Addon.

Lightweight Flask server that handles Garmin login, MFA, status checks,
and logout. Shares the same token file as garmin-sync.py.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import gcal
import interactions
from flask import Flask, Response, jsonify, request
from mfa_store import MfaStore
from request_user import USER_ID_HEADER, resolve_user_id
from token_paths import user_token_dir

try:
    from garminconnect import Garmin
except ImportError as exc:
    raise SystemExit("ERROR: garminconnect not installed") from exc

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("garmin-auth")

TOKEN_DIR = "/data/garmin-tokens"

# Base diagnostic sync log for single-user/addon runs (transient stdout/stderr
# of the most recent manual sync). Per-user runs get an isolated log under the
# user's token dir — see _sync_log_paths(). Module-level so tests can redirect
# these off /data.
SYNC_LOG_PATH = "/data/garmin-sync.log"
SYNC_LOG_PREV_PATH = "/data/garmin-sync.log.1"


def _token_dir(user_id: Optional[str] = None) -> str:
    """Token directory for ``user_id`` (falls back to the shared dir).

    Single-user/addon requests pass no user id and share ``TOKEN_DIR``, exactly
    as before. Multi-tenant requests get an isolated, path-safe subdirectory.
    """
    return user_token_dir(TOKEN_DIR, user_id)


def _sync_log_paths(user_id: Optional[str] = None) -> tuple[str, str]:
    """Return (log, prev_log) paths for a sync run.

    Single-user/addon → the shared /data logs (unchanged). Multi-tenant →
    per-user logs under the user's token dir so one user cannot read another
    user's sync output via /auth/sync-log.
    """
    if not user_id or not user_id.strip():
        return SYNC_LOG_PATH, SYNC_LOG_PREV_PATH
    base = _token_dir(user_id)
    return os.path.join(base, "sync.log"), os.path.join(base, "sync.log.1")


def _assert_token_dir_contained(token_dir: str) -> None:
    """Refuse a token dir that escapes TOKEN_DIR or has any symlinked component.

    Per-user dirs live at ``TOKEN_DIR/users/<hash>``. Two properties are
    enforced:

    - **Containment**: the dir must be ``TOKEN_DIR`` itself or lexically below
      it (the hashed user id can't introduce ``..``, so an abspath check is
      sufficient and avoids trusting symlink resolution).
    - **No symlinked component** from ``TOKEN_DIR`` (inclusive) down to the
      target. A symlinked component — even one resolving *within* TOKEN_DIR
      (e.g. ``users`` → ``users/<other>``) — would silently break per-user
      isolation or redirect credentials, so any such symlink is rejected.
    """
    base = os.path.abspath(TOKEN_DIR)
    target = os.path.abspath(token_dir)
    if target != base and os.path.commonpath([base, target]) != base:
        raise PermissionError(f"Refusing token dir outside base: {token_dir}")
    if os.path.islink(base):
        raise PermissionError(f"Refusing symlinked base token dir: {base}")
    rel = os.path.relpath(target, base)
    if rel != ".":
        current = base
        for part in rel.split(os.sep):
            current = os.path.join(current, part)
            if os.path.islink(current):
                raise PermissionError(
                    f"Refusing symlinked token-dir component: {current}"
                )


def _req_user_id() -> Optional[str]:
    """Resolve the acting user id from the current request (header or body)."""
    return resolve_user_id(
        request.headers.get(USER_ID_HEADER),
        request.get_json(silent=True),
    )


def _read_text_nofollow(path: str) -> str:
    """Read a file read-only, refusing to follow a symlink at the final path.

    Status/log files live under dirs that may be writable in some deployments;
    a pre-planted symlink there could otherwise redirect a read to an arbitrary
    file. Raises OSError (ELOOP) if the path is a symlink — callers already
    handle read errors gracefully.
    """
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "r") as f:
        return f.read()


# Pending MFA state, isolated per user (empty key == single-user addon).
_mfa_store = MfaStore()


def _has_saved_garmin_tokens(
    token_dir: str | None = None, user_id: Optional[str] = None
) -> bool:
    """Return true if either native or legacy Garmin token files exist."""
    token_dir = token_dir or _token_dir(user_id)
    return os.path.exists(os.path.join(token_dir, "garmin_tokens.json")) or (
        os.path.exists(os.path.join(token_dir, "oauth1_token.json"))
        and os.path.exists(os.path.join(token_dir, "oauth2_token.json"))
    )


def _save_tokens(client: "Garmin", user_id: Optional[str] = None) -> None:
    """Save garth tokens to disk in native directory format."""
    token_dir = _token_dir(user_id)
    # Refuse before creating anything if the resolved dir escapes the base via
    # a symlinked component, then never write through a symlinked dir — both
    # could redirect credentials.
    _assert_token_dir_contained(token_dir)
    os.makedirs(token_dir, mode=0o700, exist_ok=True)
    if os.path.islink(token_dir):
        raise PermissionError(f"Token directory is a symlink: {token_dir}")
    os.chmod(token_dir, 0o700)
    client.garth.dump(token_dir)
    # Restrict token files to owner-only — they are credential material and
    # the data dir may be reachable by other add-ons. Skip symlinks so a
    # pre-planted link cannot redirect the chmod to an unrelated file.
    for name in os.listdir(token_dir):
        path = os.path.join(token_dir, name)
        if os.path.isfile(path) and not os.path.islink(path):
            os.chmod(path, 0o600)
    log.info("Tokens saved to %s", token_dir)


def _load_client(user_id: Optional[str] = None) -> Optional["Garmin"]:
    """Load a Garmin client from saved tokens. Returns None on failure."""
    token_dir = _token_dir(user_id)
    try:
        # Never read credentials through a symlink-escaped dir.
        _assert_token_dir_contained(token_dir)
    except PermissionError:
        return None
    if not os.path.exists(token_dir):
        return None
    try:
        email = os.environ.get("GARMIN_EMAIL", "")
        client = Garmin(email or "check")
        client.login(tokenstore=token_dir)
        return client
    except Exception as exc:
        log.debug("Failed to load client from tokens: %s", exc)
        return None


@app.route("/auth/login", methods=["POST"])
def login() -> tuple[Response, int] | Response:
    """Attempt Garmin Connect login. Returns MFA prompt if required."""
    data = request.get_json(silent=True) or {}
    user_id = _req_user_id()
    email = data.get("email", "").strip()
    password = data.get("password", "")

    if not email or not password:
        return jsonify(success=False, message="Email and password are required"), 400

    try:
        log.info("Attempting Garmin login for %s", email)
        client = Garmin(email, password, return_on_mfa=True)
        result = client.login()

        log.info("Login result type: %s", type(result).__name__)

        # return_on_mfa=True: login() returns ("needs_mfa", client_state)
        # when MFA is required, or (oauth1, oauth2) on success
        if isinstance(result, tuple) and len(result) == 2:
            token1, token2 = result
            log.info("Login returned tuple: token1 type=%s", type(token1).__name__)
            if token1 == "needs_mfa":
                _mfa_store.set(user_id, {
                    "email": email,
                    "password": password,
                    "client_state": token2,
                    "client": client,
                })
                log.info("MFA required — saved client state and credentials")
                return jsonify(success=False, needsMfa=True,
                               message="MFA code required")

        # Login succeeded — persist tokens
        _save_tokens(client, user_id)
        _mfa_store.clear(user_id)
        return jsonify(success=True, needsMfa=False)

    except Exception as exc:
        log.warning("Login exception: %s", exc)
        msg = str(exc).lower()
        if "mfa" in msg or "verification" in msg or "two-factor" in msg:
            # Save credentials for retry via MFA endpoint
            _mfa_store.set(user_id, {
                "email": email,
                "password": password,
                "client_state": None,
                "client": None,
            })
            log.info("MFA detected via exception — saved credentials for retry")
            return jsonify(success=False, needsMfa=True,
                           message="MFA code required")
        return jsonify(success=False, needsMfa=False,
                       message=f"Login failed: {exc}"), 401


@app.route("/auth/mfa", methods=["POST"])
def mfa() -> tuple[Response, int] | Response:
    """Complete MFA verification and save token."""
    data = request.get_json(silent=True) or {}
    user_id = _req_user_id()
    code = data.get("code", "").strip()
    if not code:
        return jsonify(success=False, message="MFA code is required"), 400

    pending = _mfa_store.get(user_id) or {}
    client_state = pending.get("client_state")
    client = pending.get("client")
    email = pending.get("email")
    password = pending.get("password")

    log.info("MFA attempt — have client_state=%s, have client=%s, have creds=%s",
             client_state is not None, client is not None, email is not None)

    # Strategy 1: Use garth.sso.resume_login with saved client_state
    if client_state and client:
        try:
            from garth import sso as garth_sso
            log.info("Trying garth.sso.resume_login...")
            oauth1, oauth2 = garth_sso.resume_login(client_state, code)
            client.garth.oauth1_token = oauth1
            client.garth.oauth2_token = oauth2
            _save_tokens(client, user_id)
            _mfa_store.clear(user_id)
            log.info("MFA success via resume_login")
            return jsonify(success=True)
        except Exception as exc:
            log.warning("resume_login failed: %s — trying fallback", exc)

    # Strategy 2: Fresh login with prompt_mfa callback
    if email and password:
        try:
            log.info("Trying fresh login with MFA code for %s...", email)
            client2 = Garmin(email, password, prompt_mfa=lambda: code)
            client2.login()
            _save_tokens(client2, user_id)
            _mfa_store.clear(user_id)
            log.info("MFA success via prompt_mfa callback")
            return jsonify(success=True)
        except Exception as exc:
            log.error("prompt_mfa login failed: %s", exc)
            _mfa_store.clear(user_id)
            return jsonify(success=False,
                           message=f"MFA failed: {exc}. "
                           "Please try logging in again."), 401

    _mfa_store.clear(user_id)
    return jsonify(success=False,
                   message="No pending MFA session. Please log in again."), 400


@app.route("/auth/status", methods=["GET"])
def status() -> Response:
    """Check whether a valid Garmin session token exists."""
    user_id = _req_user_id()
    token_dir = _token_dir(user_id)
    client = _load_client(user_id)
    if client is None:
        return jsonify(connected=False, email="", lastSync="")

    try:
        email = os.environ.get("GARMIN_EMAIL", "")
        # Prefer last successful data sync timestamp (written by garmin-sync.py)
        # falling back to token directory mtime when that file is missing
        # (fresh install before first sync completes).
        last_sync_file = os.path.join(token_dir, ".last_sync")
        last_modified = None
        try:
            last_modified = _read_text_nofollow(last_sync_file).strip()
        except OSError:
            last_modified = None
        if not last_modified:
            stat = os.stat(token_dir)
            last_modified = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat()
        return jsonify(connected=True, email=email, lastSync=last_modified)
    except Exception:
        return jsonify(connected=False, email="", lastSync="")


@app.route("/auth/sync-status", methods=["GET"])
def sync_status() -> Response:
    """Return current sync progress."""
    try:
        token_dir = _token_dir(_req_user_id())
        _assert_token_dir_contained(token_dir)
        status_file = os.path.join(token_dir, ".sync_status")
        if os.path.exists(status_file):
            with open(status_file) as f:
                data = json.load(f)
            return jsonify(**data)
    except Exception:
        pass
    return jsonify(syncing=False, phase="idle", detail="", progress=100)


@app.route("/auth/sync-log", methods=["GET"])
def sync_log() -> Response:
    """Return the tail of the most recent manual-sync log for diagnosis."""
    user_id = _req_user_id()
    try:
        # Never read another user's log via a symlink-escaped token dir.
        _assert_token_dir_contained(_token_dir(user_id))
    except PermissionError:
        return jsonify(available=False, log="(no sync log yet)")
    log_path, prev_log_path = _sync_log_paths(user_id)
    try:
        lines: list[str] = []
        if os.path.exists(prev_log_path):
            lines.extend(_read_text_nofollow(prev_log_path).splitlines(True)[-200:])
        if os.path.exists(log_path):
            lines.extend(_read_text_nofollow(log_path).splitlines(True)[-400:])
        if not lines:
            return jsonify(available=False, log="(no sync log yet)")
        return jsonify(available=True, log="".join(lines[-500:]))
    except OSError as exc:
        return jsonify(available=False, log=f"(error reading log: {exc})")


@app.route("/auth/sync", methods=["POST"])
def trigger_sync() -> tuple[Response, int] | Response:
    """Trigger an immediate Garmin sync in the background."""
    import subprocess

    user_id = _req_user_id()
    token_dir = _token_dir(user_id)

    # Refuse if the resolved token dir escapes the base via a symlinked
    # component before we read status files or launch a scoped sync there.
    try:
        _assert_token_dir_contained(token_dir)
    except PermissionError:
        return jsonify(success=False, message="Invalid token directory"), 500

    # Check if sync is already running
    status_file = os.path.join(token_dir, ".sync_status")
    try:
        if os.path.exists(status_file):
            with open(status_file) as f:
                data = json.load(f)
            if data.get("syncing"):
                return jsonify(success=False, message="Sync already in progress"), 409
    except Exception:
        pass

    # Check if either native garminconnect tokens or legacy garth tokens exist.
    if not _has_saved_garmin_tokens(user_id=user_id):
        return jsonify(success=False, message="Not connected to Garmin"), 400

    # Launch sync in background. Capture stdout/stderr to a rotated log so
    # failures (e.g. garminconnect list-wrap regressions, API errors) are
    # surfaced for diagnosis instead of being silently discarded.
    try:
        env = os.environ.copy()
        env["DATABASE_URL"] = os.environ.get(
            "DATABASE_URL",
            "postgresql://postgres@127.0.0.1:5432/pulsecoach"
        )
        # Scope the sync to this user: the sync script reads GARMIN_TOKEN_DIR
        # for tokens and GARMIN_USER_ID for the row owner. When no user id is
        # present (addon), both fall through to the shared defaults.
        env["GARMIN_TOKEN_DIR"] = token_dir
        if user_id:
            env["GARMIN_USER_ID"] = user_id
        # Per-user log when scoped, shared /data log for the addon.
        log_path, prev_log_path = _sync_log_paths(user_id)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        try:
            if os.path.exists(log_path):
                # Keep one rotation so the previous run's tail survives.
                if os.path.exists(prev_log_path):
                    os.remove(prev_log_path)
                os.rename(log_path, prev_log_path)
        except OSError as exc:
            log.warning("Could not rotate sync log: %s", exc)
        # Open O_NOFOLLOW so a pre-planted symlink at log_path cannot redirect
        # the sync output to an arbitrary file.
        _log_fd = os.open(
            log_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
            0o600,
        )
        log_fh = os.fdopen(_log_fd, "w", buffering=1)
        try:
            log_fh.write(
                f"=== Manual sync triggered at "
                f"{datetime.now(timezone.utc).isoformat()} ===\n"
            )
            log_fh.flush()
            subprocess.Popen(
                ["python3", "/app/scripts/garmin-sync.py"],
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
            )
        finally:
            # Child inherits the fd; the parent can safely close its handle
            # to avoid leaking an fd per /sync invocation.
            log_fh.close()
        log.info("Manual sync triggered (log: %s)", log_path)
        return jsonify(
            success=True,
            message="Sync started",
            log_path=log_path,
        )
    except Exception as exc:
        log.error("Failed to trigger sync: %s", exc)
        return jsonify(success=False, message=f"Failed to start sync: {exc}"), 500


@app.route("/auth/import-tokens", methods=["POST"])
def import_tokens() -> tuple[Response, int] | Response:
    """Import pre-generated garth tokens (oauth1 + oauth2 JSON)."""
    data = request.get_json(silent=True) or {}
    user_id = _req_user_id()
    token_dir = _token_dir(user_id)
    oauth1 = data.get("oauth1_token")
    oauth2 = data.get("oauth2_token")

    if not oauth1 or not oauth2:
        return jsonify(success=False,
                       message="Both oauth1_token and oauth2_token required"), 400

    try:
        # Defense-in-depth: refuse *before* creating anything if the resolved
        # dir escapes the base via a symlinked component — otherwise makedirs
        # would create a dir at the attacker-controlled target.
        _assert_token_dir_contained(token_dir)
        os.makedirs(token_dir, mode=0o700, exist_ok=True)
        # Also refuse if token_dir itself is a symlink.
        if os.path.islink(token_dir):
            return jsonify(
                success=False,
                message="Token directory is a symlink; refusing to import",
            ), 500
        os.chmod(token_dir, 0o700)
        # Owner-only token files, O_NOFOLLOW so a pre-planted symlink
        # cannot redirect the write to an unrelated file.
        for name, payload in (("oauth1_token.json", oauth1),
                              ("oauth2_token.json", oauth2)):
            fd = os.open(
                os.path.join(token_dir, name),
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f)
            os.chmod(os.path.join(token_dir, name), 0o600)

        # Verify tokens work
        client = _load_client(user_id)
        if client is None:
            return jsonify(success=False,
                           message="Tokens saved but validation failed"), 500

        return jsonify(success=True, message="Tokens imported and verified")

    except Exception as exc:
        return jsonify(success=False, message=f"Import failed: {exc}"), 500


@app.route("/auth/logout", methods=["POST"])
def logout() -> tuple[Response, int] | Response:
    """Remove stored Garmin session token."""
    try:
        import shutil
        user_id = _req_user_id()
        token_dir = _token_dir(user_id)
        # Refuse to rmtree a dir that escapes the base via a symlinked
        # component (could delete data outside TOKEN_DIR).
        _assert_token_dir_contained(token_dir)
        _mfa_store.clear(user_id)
        if os.path.exists(token_dir):
            shutil.rmtree(token_dir)
        return jsonify(success=True)
    except Exception as exc:
        return jsonify(success=False, message=str(exc)), 500


@app.route("/auth/recompute", methods=["POST"])
def trigger_recompute() -> tuple[Response, int] | Response:
    """Trigger an immediate metrics recomputation in the background."""
    import subprocess
    import time

    status_file = os.path.join(TOKEN_DIR, ".recompute_status")
    try:
        if os.path.exists(status_file):
            with open(status_file) as f:
                data = json.load(f)
            if data.get("running"):
                return jsonify(success=False, message="Recompute already running"), 409
    except Exception:
        pass

    try:
        # Write running status
        with open(status_file, "w") as f:
            json.dump({"running": True, "started": time.time()}, f)

        env = os.environ.copy()
        env["DATABASE_URL"] = os.environ.get(
            "DATABASE_URL",
            "postgresql://postgres@127.0.0.1:5432/pulsecoach",
        )
        subprocess.Popen(
            ["python3", "/app/scripts/metrics-compute.py", "--once"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info("Manual recompute triggered")
        return jsonify(success=True, message="Recompute started")
    except Exception as exc:
        # Clean up status file on Popen failure
        try:
            with open(status_file, "w") as f:
                json.dump({"running": False, "error": str(exc)}, f)
        except OSError:
            pass
        log.error("Failed to trigger recompute: %s", exc)
        return jsonify(success=False, message=f"Failed: {exc}"), 500


@app.route("/auth/recompute-status", methods=["GET"])
def recompute_status() -> Response:
    """Check if metrics recompute is currently running."""
    status_file = os.path.join(TOKEN_DIR, ".recompute_status")
    try:
        if os.path.exists(status_file):
            with open(status_file) as f:
                return jsonify(json.load(f))
    except Exception:
        pass
    return jsonify({"running": False})


@app.route("/auth/meeting-stress", methods=["POST"])
def trigger_meeting_stress() -> tuple[Response, int] | Response:
    """Score calendar meetings against Garmin HR (background run).

    Calendar source: a linked Google Calendar (/data/gcal-token.json) or a
    calendar_events.json dropped in /share/pulsecoach/. Results are written
    back to /share/pulsecoach/.
    """
    import subprocess
    import time

    events_file = "/share/pulsecoach/calendar_events.json"
    gcal_linked = (os.path.exists("/data/gcal-token.json")
                   or os.path.exists("/share/pulsecoach/gcal-token.json"))
    if not os.path.exists(events_file) and not gcal_linked:
        return jsonify(
            success=False,
            message="No calendar source: link Google Calendar "
                    "(scripts/generate-gcal-token.py) or drop "
                    f"calendar_events.json at {events_file}",
        ), 400
    has_tokens = any(
        os.path.exists(os.path.join(TOKEN_DIR, name))
        for name in ("garmin_tokens.json", "oauth1_token.json", "oauth2_token.json")
    )
    if not has_tokens:
        return jsonify(success=False, message="Not connected to Garmin"), 400

    status_file = os.path.join(TOKEN_DIR, ".meeting_stress_status")
    try:
        if os.path.exists(status_file):
            with open(status_file) as f:
                if json.load(f).get("running"):
                    return jsonify(success=False, message="Already running"), 409
    except Exception:
        pass

    try:
        with open(status_file, "w") as f:
            json.dump({"running": True, "started": time.time()}, f)
        log_fh = open("/data/meeting-stress.log", "w", buffering=1)
        try:
            # Script resolves the source: linked calendar > dropped events file.
            # Lookback window comes from the addon's meeting_lookback_days
            # option (default 30); more history = better per-person stats.
            cmd = ["python3", "/app/scripts/meeting-stress.py",
                   "--fetch", "--no-color"]
            raw_days = os.environ.get("MEETING_LOOKBACK_DAYS", "").strip()
            try:
                days = int(raw_days)
            except ValueError:
                days = 0
            if days > 0:
                # Mirror the addon schema's 1–365 bound so a mis-set env can't
                # trigger an unexpectedly long run.
                cmd += ["--days", str(min(days, 365))]
            subprocess.Popen(
                cmd,
                env=os.environ.copy(),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
            )
        finally:
            log_fh.close()
        log.info("Meeting stress run triggered")
        return jsonify(success=True, message="Meeting stress run started",
                       results="/share/pulsecoach/meeting_stress.json")
    except Exception as exc:
        try:
            with open(status_file, "w") as f:
                json.dump({"running": False, "error": str(exc)}, f)
        except OSError:
            pass
        log.error("Failed to trigger meeting stress: %s", exc)
        return jsonify(success=False, message=f"Failed: {exc}"), 500


@app.route("/auth/meeting-stress-status", methods=["GET"])
def meeting_stress_status() -> Response:
    """Running state + latest leaderboard, if any."""
    out: dict = {
        "running": False,
        "calendar_linked": os.path.exists("/data/gcal-token.json")
        or os.path.exists("/share/pulsecoach/gcal-token.json"),
        "events_file": os.path.exists("/share/pulsecoach/calendar_events.json"),
    }
    status_file = os.path.join(TOKEN_DIR, ".meeting_stress_status")
    try:
        if os.path.exists(status_file):
            with open(status_file) as f:
                out.update(json.load(f))
    except Exception:
        pass
    try:
        results = "/share/pulsecoach/meeting_stress.json"
        if os.path.exists(results):
            with open(results) as f:
                out["results"] = json.load(f)
    except Exception:
        pass
    return jsonify(out)


@app.route("/auth/gcal-link", methods=["POST"])
def gcal_link() -> tuple[Response, int] | Response:
    """Link a Google Calendar by pasting a generate-gcal-token.py token.

    Body: {client_id, client_secret, refresh_token}. The credentials are
    verified against Google (a real refresh) before being written owner-only
    to /data, so a bad paste fails loudly instead of silently at run time.
    """
    data = request.get_json(silent=True) or {}
    client_id = str(data.get("client_id", "")).strip()
    client_secret = str(data.get("client_secret", "")).strip()
    refresh_token = str(data.get("refresh_token", "")).strip()
    if not (client_id and client_secret and refresh_token):
        return jsonify(
            success=False,
            message="Paste the full gcal-token.json "
                    "(client_id, client_secret, refresh_token).",
        ), 400
    try:
        gcal.validate_token(client_id, client_secret, refresh_token)
    except gcal.GcalError as exc:
        return jsonify(success=False,
                       message=f"Google rejected the token: {exc}"), 400
    try:
        gcal.save_token(client_id, client_secret, refresh_token)
    except gcal.GcalError as exc:
        return jsonify(success=False, message=str(exc)), 500
    # A successful refresh doesn't guarantee Calendar read scope, so probe the
    # Calendar API now. If it fails, unlink so the UI never claims "linked"
    # while the board would later fail to fetch events.
    try:
        gcal.list_calendars()
    except gcal.GcalError as exc:
        gcal.unlink()
        return jsonify(
            success=False,
            message=f"Token lacks Google Calendar access: {exc}",
        ), 400
    log.info("Google Calendar linked via UI")
    return jsonify(success=True, message="Google Calendar linked")


@app.route("/auth/gcal-unlink", methods=["POST"])
def gcal_unlink() -> tuple[Response, int] | Response:
    """Remove the linked Google Calendar token and calendar selection."""
    try:
        gcal.unlink()
        return jsonify(success=True, message="Google Calendar unlinked")
    except OSError as exc:
        return jsonify(success=False, message=str(exc)), 500


@app.route("/auth/gcal-calendars", methods=["GET", "POST"])
def gcal_calendars() -> tuple[Response, int] | Response:
    """List the account's calendars (GET) or save the selection (POST).

    GET returns [{id, summary, primary, selected}]; POST accepts
    {calendar_ids: [...]} and persists which calendars feed the Stress Board.
    """
    if not gcal.linked():
        return jsonify(success=False,
                       message="No Google Calendar linked"), 400
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        ids = data.get("calendar_ids")
        if not isinstance(ids, list):
            return jsonify(success=False,
                           message="calendar_ids must be a list"), 400
        try:
            gcal.save_selected([str(x) for x in ids])
        except gcal.GcalError as exc:
            return jsonify(success=False, message=str(exc)), 500
        return jsonify(success=True, message="Calendar selection saved")
    try:
        return jsonify(success=True, calendars=gcal.list_calendars())
    except gcal.GcalError as exc:
        return jsonify(success=False, message=str(exc)), 502


@app.route("/auth/interactions", methods=["GET", "POST"])
def interactions_route() -> tuple[Response, int] | Response:
    """List recent interactions (GET) or quick-add one (POST).

    POST body: {person, minutes, end?} — end defaults to now. Backs the
    Stress Board's in-app quick-add so out-of-calendar contacts no longer
    require hand-writing JSONL via an HA shell_command.
    """
    if request.method == "POST":
        data = request.get_json(silent=True)
        if not isinstance(data, dict):  # a JSON array/scalar has no .get()
            data = {}
        try:
            rec = interactions.add_interaction(
                data.get("person", ""),
                data.get("minutes"),
                data.get("end") or None,
            )
        except interactions.InteractionError as exc:
            return jsonify(success=False, message=str(exc)), 400
        except OSError as exc:
            return jsonify(success=False, message=str(exc)), 500
        return jsonify(success=True, interaction=rec)
    return jsonify(success=True,
                   interactions=interactions.list_interactions())


@app.route("/auth/interactions/<iid>", methods=["DELETE"])
def interactions_delete(iid: str) -> tuple[Response, int] | Response:
    """Delete one logged interaction by id."""
    try:
        if interactions.delete_interaction(iid):
            return jsonify(success=True, message="Interaction removed")
    except OSError as exc:
        return jsonify(success=False, message=str(exc)), 500
    return jsonify(success=False, message="Interaction not found"), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8099)
