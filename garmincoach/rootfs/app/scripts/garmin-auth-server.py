#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Garmin Connect authentication microservice for GarminCoach HA Addon.

Lightweight Flask server that handles Garmin login, MFA, status checks,
and logout. Shares the same token file as garmin-sync.py.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from flask import Flask, Response, jsonify, request

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


def _save_tokens(client: "Garmin") -> None:
    """Save garth tokens to disk in native directory format."""
    os.makedirs(TOKEN_DIR, exist_ok=True)
    client.garth.dump(TOKEN_DIR)
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
        # Check for last sync time from token dir modification
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

    # Check if tokens exist
    if not os.path.exists(os.path.join(TOKEN_DIR, "oauth1_token.json")):
        return jsonify(success=False, message="Not connected to Garmin"), 400

    # Launch sync in background
    try:
        env = os.environ.copy()
        env["DATABASE_URL"] = os.environ.get(
            "DATABASE_URL",
            "postgresql://postgres@127.0.0.1:5432/garmincoach"
        )
        subprocess.Popen(
            ["python3", "/app/scripts/garmin-sync.py"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info("Manual sync triggered")
        return jsonify(success=True, message="Sync started")
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
        os.makedirs(TOKEN_DIR, exist_ok=True)
        with open(os.path.join(TOKEN_DIR, "oauth1_token.json"), "w") as f:
            json.dump(oauth1, f)
        with open(os.path.join(TOKEN_DIR, "oauth2_token.json"), "w") as f:
            json.dump(oauth2, f)

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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8099)
