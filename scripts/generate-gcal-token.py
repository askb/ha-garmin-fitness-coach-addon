#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
##############################################################################
# One-time Google Calendar OAuth for the meeting stress leaderboard.
#
# Prereq (5 min, once): create a Google Cloud project, enable the Calendar
# API, create an OAuth client of type "Desktop app", note client id + secret.
#
# Runs the browser loopback flow with the read-only calendar scope and writes
# gcal-token.json (client id/secret + refresh token). Copy that file to
# /share/pulsecoach/ on HAOS — the addon adopts it into /data on first run.
#
# stdlib only: the loopback listener is a plain http.server; token exchange
# is urllib. No google-auth dependency for a one-shot helper.
##############################################################################
"""Generate a Google Calendar refresh token for PulseCoach meeting stress."""

from __future__ import annotations

import http.server
import json
import secrets
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PORT = 8765
OUT_FILE = "gcal-token.json"


def _load_creds() -> tuple[str, str]:
    """Client id+secret from a downloaded client_secret_*.json arg, or prompts."""
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            data = json.load(f)
        blob = data.get("installed") or data.get("web") or {}
        cid, csec = blob.get("client_id", ""), blob.get("client_secret", "")
        if cid and csec:
            if "web" in data:
                print("NOTE: this is a 'web' OAuth client — make sure "
                      f"http://127.0.0.1:{PORT} is in its Authorized redirect URIs.")
            return cid, csec
        print(f"Could not find client_id/secret in {sys.argv[1]}")
    return input("OAuth client ID: ").strip(), input("OAuth client secret: ").strip()


def main() -> int:
    client_id, client_secret = _load_creds()
    state = secrets.token_urlsafe(16)
    redirect_uri = f"http://127.0.0.1:{PORT}"
    code_holder: dict = {}
    got_callback = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if qs.get("state", [""])[0] == state and "code" in qs:
                code_holder["code"] = qs["code"][0]
                msg = b"Linked! You can close this tab."
            else:
                msg = b"Missing/invalid code."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(msg)
            got_callback.set()

        def log_message(self, *a):  # silence request logging
            pass

    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()

    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",   # ask for a refresh token
        "prompt": "consent",        # force refresh token even if previously granted
        "state": state,
    })
    url = f"{AUTH_URL}?{params}"
    print(f"\nOpening browser for consent...\n{url}\n")
    webbrowser.open(url)
    print("Waiting for browser approval (up to 5 minutes)...")
    got_callback.wait(timeout=300)

    code = code_holder.get("code")
    if not code:
        print("No authorization code received. If your Workspace admin blocks "
              "unapproved apps you'll have seen an error page — fall back to "
              "the ICS export flow (scripts/ics_to_events.py).")
        return 1

    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body)) as resp:
        tok = json.load(resp)

    refresh = tok.get("refresh_token")
    if not refresh:
        print("Token response had no refresh_token — re-run (prompt=consent should force it).")
        return 1

    with open(OUT_FILE, "w") as f:
        json.dump({"client_id": client_id, "client_secret": client_secret,
                   "refresh_token": refresh}, f, indent=1)
    print(f"\n✓ Wrote {OUT_FILE}")
    print("Copy it to HAOS:  scp gcal-token.json <haos>:/share/pulsecoach/")
    print("The addon moves it into /data (private) on the next meeting-stress run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
