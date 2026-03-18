#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Garmin Connect authentication microservice for GarminCoach HA Addon.

Lightweight Flask server that handles Garmin login, MFA, status checks,
and logout. Shares the same token file as garmin-sync.py.
"""

import json
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request

try:
    from garminconnect import Garmin
except ImportError as exc:
    raise SystemExit("ERROR: garminconnect not installed") from exc

app = Flask(__name__)

TOKEN_DIR = "/data/garmin-tokens"
TOKEN_FILE = os.path.join(TOKEN_DIR, "session.json")

# Hold pending MFA state (single-user addon, no sessions needed)
_pending_client_state = None
_pending_garmin_client = None


def _save_tokens(client):
    """Save garth tokens to disk in native directory format."""
    os.makedirs(TOKEN_DIR, exist_ok=True)
    client.garth.dump(TOKEN_DIR)


def _load_client():
    """Load a Garmin client from saved tokens. Returns None on failure."""
    if not os.path.exists(TOKEN_DIR):
        return None
    try:
        email = os.environ.get("GARMIN_EMAIL", "")
        client = Garmin(email or "check")
        client.login(tokenstore=TOKEN_DIR)
        return client
    except Exception:
        return None


@app.route("/auth/login", methods=["POST"])
def login():
    """Attempt Garmin Connect login. Returns MFA prompt if required."""
    global _pending_client_state  # noqa: PLW0603

    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip()
    password = data.get("password", "")

    if not email or not password:
        return jsonify(success=False, message="Email and password are required"), 400

    try:
        client = Garmin(email, password, return_on_mfa=True)
        result = client.login()

        # return_on_mfa=True: login() returns ("needs_mfa", client_state)
        # when MFA is required, or (oauth1, oauth2) on success
        if isinstance(result, tuple) and len(result) == 2:
            token1, token2 = result
            if token1 == "needs_mfa":
                # token2 is the client_state dict for resume_login()
                _pending_client_state = token2
                _pending_garmin_client = client
                return jsonify(success=False, needsMfa=True,
                               message="MFA code required")

        # Login succeeded — persist token as directory (garth native format)
        _save_tokens(client)
        _pending_client_state = None
        return jsonify(success=True, needsMfa=False)

    except Exception as exc:
        msg = str(exc).lower()
        if "mfa" in msg or "verification" in msg or "two-factor" in msg:
            return jsonify(success=False, needsMfa=True,
                           message="MFA code required")
        return jsonify(success=False, needsMfa=False,
                       message=f"Login failed: {exc}"), 401


@app.route("/auth/mfa", methods=["POST"])
def mfa():
    """Complete MFA verification and save token."""
    global _pending_client_state  # noqa: PLW0603
    global _pending_garmin_client  # noqa: PLW0603

    if _pending_client_state is None:
        return jsonify(success=False, message="No pending MFA session. "
                       "Please re-enter email and password first."), 400

    data = request.get_json(silent=True) or {}
    code = data.get("code", "").strip()
    if not code:
        return jsonify(success=False, message="MFA code is required"), 400

    try:
        from garth import sso as garth_sso

        # Use garth.sso.resume_login directly with the saved client state
        oauth1, oauth2 = garth_sso.resume_login(_pending_client_state, code)

        # Attach tokens to the garmin client's garth instance
        _pending_garmin_client.garth.oauth1_token = oauth1
        _pending_garmin_client.garth.oauth2_token = oauth2
        _save_tokens(_pending_garmin_client)

        _pending_client_state = None
        _pending_garmin_client = None
        return jsonify(success=True)

    except Exception as exc:
        _pending_client_state = None
        _pending_garmin_client = None
        return jsonify(success=False,
                       message=f"MFA failed: {exc}. "
                       "Session may have expired — try logging in again quickly."), 401


@app.route("/auth/status", methods=["GET"])
def status():
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


@app.route("/auth/import-tokens", methods=["POST"])
def import_tokens():
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
def logout():
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
