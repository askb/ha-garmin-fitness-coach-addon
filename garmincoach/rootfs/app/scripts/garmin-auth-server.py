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

# Hold a pending client during MFA flow (single-user addon, no sessions needed)
_pending_client = None


@app.route("/auth/login", methods=["POST"])
def login():
    """Attempt Garmin Connect login. Returns MFA prompt if required."""
    global _pending_client  # noqa: PLW0603

    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip()
    password = data.get("password", "")

    if not email or not password:
        return jsonify(success=False, message="Email and password are required"), 400

    try:
        client = Garmin(email, password)
        client.login()

        # Login succeeded without MFA — persist token
        os.makedirs(TOKEN_DIR, exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            json.dump(client.garth.dumps(), f)

        _pending_client = None
        return jsonify(success=True, needsMfa=False)

    except Exception as exc:
        msg = str(exc).lower()
        if "mfa" in msg or "verification" in msg or "two-factor" in msg:
            _pending_client = client
            return jsonify(success=False, needsMfa=True, message="MFA code required")
        return jsonify(success=False, needsMfa=False, message=str(exc)), 401


@app.route("/auth/mfa", methods=["POST"])
def mfa():
    """Complete MFA verification and save token."""
    global _pending_client  # noqa: PLW0603

    if _pending_client is None:
        return jsonify(success=False, message="No pending MFA session"), 400

    data = request.get_json(silent=True) or {}
    code = data.get("code", "").strip()
    if not code:
        return jsonify(success=False, message="MFA code is required"), 400

    try:
        _pending_client.login(mfa_code=code)

        os.makedirs(TOKEN_DIR, exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            json.dump(_pending_client.garth.dumps(), f)

        _pending_client = None
        return jsonify(success=True)

    except Exception as exc:
        _pending_client = None
        return jsonify(success=False, message=str(exc)), 401


@app.route("/auth/status", methods=["GET"])
def status():
    """Check whether a valid Garmin session token exists."""
    if not os.path.exists(TOKEN_FILE):
        return jsonify(connected=False, email="", lastSync="")

    try:
        stat = os.stat(TOKEN_FILE)
        last_modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

        with open(TOKEN_FILE) as f:
            token_data = json.load(f)

        # Validate token by creating a client and checking login
        email = os.environ.get("GARMIN_EMAIL", "")
        client = Garmin(email or "check", "")
        client.login(tokenstore=token_data)

        return jsonify(connected=True, email=email, lastSync=last_modified)

    except Exception:
        return jsonify(connected=False, email="", lastSync="")


@app.route("/auth/logout", methods=["POST"])
def logout():
    """Remove stored Garmin session token."""
    try:
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
        return jsonify(success=True)
    except Exception as exc:
        return jsonify(success=False, message=str(exc)), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8099)
