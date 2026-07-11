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

from flask import Flask, Response, jsonify, request

import gcal
import interactions

try:
    from garminconnect import Garmin
except ImportError as exc:
    raise SystemExit("ERROR: garminconnect not installed") from exc

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("garmin-auth")

TOKEN_DIR = "/data/garmin-tokens"
TOKEN_FILE = os.path.join(TOKEN_DIR, "session.json")

# Hold pending MFA state (single-user addon)
_mfa_state = {
    "email": None,
    "password": None,
    "client_state": None,
    "client": None,
}


def _has_saved_garmin_tokens(token_dir: str | None = None) -> bool:
    """Return true if either native or legacy Garmin token files exist."""
    token_dir = token_dir or TOKEN_DIR
    return os.path.exists(os.path.join(token_dir, "garmin_tokens.json")) or (
        os.path.exists(os.path.join(token_dir, "oauth1_token.json"))
        and os.path.exists(os.path.join(token_dir, "oauth2_token.json"))
    )


def _save_tokens(client: "Garmin") -> None:
    """Save garth tokens to disk in native directory format."""
    os.makedirs(TOKEN_DIR, mode=0o700, exist_ok=True)
    # Don't chmod through a symlink — only tighten a real directory.
    if not os.path.islink(TOKEN_DIR):
        os.chmod(TOKEN_DIR, 0o700)
    client.garth.dump(TOKEN_DIR)
    # Restrict token files to owner-only — they are credential material and
    # the data dir may be reachable by other add-ons. Skip symlinks so a
    # pre-planted link cannot redirect the chmod to an unrelated file.
    for name in os.listdir(TOKEN_DIR):
        path = os.path.join(TOKEN_DIR, name)
        if os.path.isfile(path) and not os.path.islink(path):
            os.chmod(path, 0o600)
    log.info("Tokens saved to %s", TOKEN_DIR)


def _load_client() -> Optional["Garmin"]:
    """Load a Garmin client from saved tokens. Returns None on failure."""
    if not os.path.exists(TOKEN_DIR):
        return None
    try:
        email = os.environ.get("GARMIN_EMAIL", "")
        client = Garmin(email or "check")
        client.login(tokenstore=TOKEN_DIR)
        return client
    except Exception as exc:
        log.debug("Failed to load client from tokens: %s", exc)
        return None


@app.route("/auth/login", methods=["POST"])
def login() -> tuple[Response, int] | Response:
    """Attempt Garmin Connect login. Returns MFA prompt if required."""
    global _mfa_state  # noqa: PLW0603

    data = request.get_json(silent=True) or {}
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
                _mfa_state = {
                    "email": email,
                    "password": password,
                    "client_state": token2,
                    "client": client,
                }
                log.info("MFA required — saved client state and credentials")
                return jsonify(success=False, needsMfa=True,
                               message="MFA code required")

        # Login succeeded — persist tokens
        _save_tokens(client)
        _mfa_state = {"email": None, "password": None,
                      "client_state": None, "client": None}
        return jsonify(success=True, needsMfa=False)

    except Exception as exc:
        log.warning("Login exception: %s", exc)
        msg = str(exc).lower()
        if "mfa" in msg or "verification" in msg or "two-factor" in msg:
            # Save credentials for retry via MFA endpoint
            _mfa_state = {
                "email": email,
                "password": password,
                "client_state": None,
                "client": None,
            }
            log.info("MFA detected via exception — saved credentials for retry")
            return jsonify(success=False, needsMfa=True,
                           message="MFA code required")
        return jsonify(success=False, needsMfa=False,
                       message=f"Login failed: {exc}"), 401


@app.route("/auth/mfa", methods=["POST"])
def mfa() -> tuple[Response, int] | Response:
    """Complete MFA verification and save token."""
    global _mfa_state  # noqa: PLW0603

    data = request.get_json(silent=True) or {}
    code = data.get("code", "").strip()
    if not code:
        return jsonify(success=False, message="MFA code is required"), 400

    client_state = _mfa_state.get("client_state")
    client = _mfa_state.get("client")
    email = _mfa_state.get("email")
    password = _mfa_state.get("password")

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
            _save_tokens(client)
            _mfa_state = {"email": None, "password": None,
                          "client_state": None, "client": None}
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
            _save_tokens(client2)
            _mfa_state = {"email": None, "password": None,
                          "client_state": None, "client": None}
            log.info("MFA success via prompt_mfa callback")
            return jsonify(success=True)
        except Exception as exc:
            log.error("prompt_mfa login failed: %s", exc)
            _mfa_state = {"email": None, "password": None,
                          "client_state": None, "client": None}
            return jsonify(success=False,
                           message=f"MFA failed: {exc}. "
                           "Please try logging in again."), 401

    _mfa_state = {"email": None, "password": None,
                  "client_state": None, "client": None}
    return jsonify(success=False,
                   message="No pending MFA session. Please log in again."), 400


@app.route("/auth/status", methods=["GET"])
def status() -> Response:
    """Check whether a valid Garmin session token exists."""
    client = _load_client()
    if client is None:
        return jsonify(connected=False, email="", lastSync="")

    try:
        email = os.environ.get("GARMIN_EMAIL", "")
        # Prefer last successful data sync timestamp (written by garmin-sync.py)
        # falling back to token directory mtime when that file is missing
        # (fresh install before first sync completes).
        last_sync_file = os.path.join(TOKEN_DIR, ".last_sync")
        last_modified = None
        try:
            with open(last_sync_file, "r") as f:
                last_modified = f.read().strip()
        except OSError:
            last_modified = None
        if not last_modified:
            stat = os.stat(TOKEN_DIR)
            last_modified = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat()
        return jsonify(connected=True, email=email, lastSync=last_modified)
    except Exception:
        return jsonify(connected=False, email="", lastSync="")


@app.route("/auth/sync-status", methods=["GET"])
def sync_status() -> Response:
    """Return current sync progress."""
    status_file = os.path.join(TOKEN_DIR, ".sync_status")
    try:
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
    log_path = "/data/garmin-sync.log"
    prev_log_path = "/data/garmin-sync.log.1"
    try:
        lines: list[str] = []
        if os.path.exists(prev_log_path):
            with open(prev_log_path) as f:
                lines.extend(f.readlines()[-200:])
        if os.path.exists(log_path):
            with open(log_path) as f:
                lines.extend(f.readlines()[-400:])
        if not lines:
            return jsonify(available=False, log="(no sync log yet)")
        return jsonify(available=True, log="".join(lines[-500:]))
    except OSError as exc:
        return jsonify(available=False, log=f"(error reading log: {exc})")


@app.route("/auth/sync", methods=["POST"])
def trigger_sync() -> tuple[Response, int] | Response:
    """Trigger an immediate Garmin sync in the background."""
    import subprocess

    # Check if sync is already running
    status_file = os.path.join(TOKEN_DIR, ".sync_status")
    try:
        if os.path.exists(status_file):
            with open(status_file) as f:
                data = json.load(f)
            if data.get("syncing"):
                return jsonify(success=False, message="Sync already in progress"), 409
    except Exception:
        pass

    # Check if either native garminconnect tokens or legacy garth tokens exist.
    if not _has_saved_garmin_tokens():
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
        log_path = "/data/garmin-sync.log"
        prev_log_path = "/data/garmin-sync.log.1"
        try:
            if os.path.exists(log_path):
                # Keep one rotation so the previous run's tail survives.
                if os.path.exists(prev_log_path):
                    os.remove(prev_log_path)
                os.rename(log_path, prev_log_path)
        except OSError as exc:
            log.warning("Could not rotate sync log: %s", exc)
        log_fh = open(log_path, "w", buffering=1)
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
    oauth1 = data.get("oauth1_token")
    oauth2 = data.get("oauth2_token")

    if not oauth1 or not oauth2:
        return jsonify(success=False,
                       message="Both oauth1_token and oauth2_token required"), 400

    try:
        os.makedirs(TOKEN_DIR, mode=0o700, exist_ok=True)
        # Defense-in-depth: if TOKEN_DIR itself is a symlink, an attacker
        # could redirect credential writes into an arbitrary directory.
        # Refuse to import rather than writing through the link.
        if os.path.islink(TOKEN_DIR):
            return jsonify(
                success=False,
                message="Token directory is a symlink; refusing to import",
            ), 500
        os.chmod(TOKEN_DIR, 0o700)
        # Owner-only token files, O_NOFOLLOW so a pre-planted symlink
        # cannot redirect the write to an unrelated file.
        for name, payload in (("oauth1_token.json", oauth1),
                              ("oauth2_token.json", oauth2)):
            fd = os.open(
                os.path.join(TOKEN_DIR, name),
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f)
            os.chmod(os.path.join(TOKEN_DIR, name), 0o600)

        # Verify tokens work
        client = _load_client()
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
        if os.path.exists(TOKEN_DIR):
            shutil.rmtree(TOKEN_DIR)
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
        data = request.get_json(silent=True) or {}
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
