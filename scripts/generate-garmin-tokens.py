#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
"""Generate Garmin Connect tokens locally and deploy to HAOS addon.

Run this on your laptop where you can interactively handle MFA.
Tokens are saved locally, then optionally copied to HAOS via SSH.

Usage:
    pip install garth garminconnect
    python scripts/generate-garmin-tokens.py

The script will:
  1. Prompt for Garmin email + password
  2. Handle MFA if your account requires it
  3. Save tokens to /tmp/garmin-tokens/
  4. Optionally copy tokens to HAOS addon via SSH
"""

import os
import sys
import shutil
import subprocess
from getpass import getpass

try:
    import garth
    from garminconnect import Garmin
except ImportError:
    print("ERROR: Missing dependencies. Run:")
    print("  pip install garth garminconnect")
    sys.exit(1)

LOCAL_TOKEN_DIR = "/tmp/garmin-tokens"
HAOS_HOST = "192.168.1.176"
HAOS_PORT = "22222"
HAOS_USER = "hassio"
ADDON_TOKEN_PATH = "/data/garmin-tokens"


def main():
    print("=== Garmin Connect Token Generator ===")
    print(f"garth version: {garth.__version__}")
    print()

    # Check for existing tokens
    if os.path.isdir(LOCAL_TOKEN_DIR):
        try:
            garth.resume(LOCAL_TOKEN_DIR)
            profile = garth.client.username
            print(f"Found existing tokens (user: {profile})")
            choice = input("Use existing tokens? [Y/n]: ").strip().lower()
            if choice != "n":
                print(f"Tokens ready at {LOCAL_TOKEN_DIR}")
                _offer_deploy()
                return
        except Exception:
            print("Existing tokens are invalid/expired, re-authenticating...")
            shutil.rmtree(LOCAL_TOKEN_DIR, ignore_errors=True)

    # Fresh login
    email = input("Garmin email: ").strip()
    if not email:
        print("ERROR: Email required")
        sys.exit(1)

    password = getpass("Garmin password: ")
    if not password:
        print("ERROR: Password required")
        sys.exit(1)

    print("\nLogging in...")
    try:
        client = Garmin(email, password, return_on_mfa=True)
        result = client.login()

        if isinstance(result, tuple) and len(result) == 2:
            token1, token2 = result
            if token1 == "needs_mfa":
                print("\n*** MFA Required ***")
                print("Check your phone/email for the verification code.")
                mfa_code = input("Enter MFA code: ").strip()

                if not mfa_code:
                    print("ERROR: MFA code required")
                    sys.exit(1)

                from garth import sso as garth_sso
                oauth1, oauth2 = garth_sso.resume_login(token2, mfa_code)
                client.garth.oauth1_token = oauth1
                client.garth.oauth2_token = oauth2
                print("MFA verified!")

        # Save tokens
        os.makedirs(LOCAL_TOKEN_DIR, exist_ok=True)
        client.garth.dump(LOCAL_TOKEN_DIR)

        # Verify
        display_name = client.get_full_name()
        print(f"\n✓ Login successful! User: {display_name}")
        print(f"✓ Tokens saved to {LOCAL_TOKEN_DIR}")

        _offer_deploy()

    except Exception as exc:
        print(f"\n✗ Login failed: {exc}")
        print("\nTroubleshooting:")
        print("  - Wait 15-30 min if rate-limited (multiple failed attempts)")
        print("  - Ensure garth >= 0.6.3: pip install --upgrade garth")
        print("  - Check https://github.com/cyberjunky/python-garminconnect/issues")
        sys.exit(1)


def _offer_deploy():
    """Offer to copy tokens to HAOS via SSH."""
    print(f"\nDeploy tokens to HAOS ({HAOS_HOST})?")
    choice = input("[Y/n]: ").strip().lower()
    if choice == "n":
        print(f"\nTo manually deploy later, re-run this script.")
        return

    print(f"Copying tokens to {HAOS_USER}@{HAOS_HOST}...")
    try:
        # HAOS hassio user can't write to /data/ directly (addon container path)
        # Instead, pipe tokens to /tmp then use the addon's import API
        for fname in os.listdir(LOCAL_TOKEN_DIR):
            src = os.path.join(LOCAL_TOKEN_DIR, fname)
            if os.path.isfile(src):
                with open(src, "r") as f:
                    content = f.read()
                subprocess.run(
                    ["ssh", "-o", "StrictHostKeyChecking=no",
                     "-p", HAOS_PORT, f"{HAOS_USER}@{HAOS_HOST}",
                     f"cat > /tmp/{fname}"],
                    input=content, check=True, capture_output=True, text=True
                )
                print(f"  ✓ Uploaded {fname}")

        # Now use the addon's import-tokens API via the ingress proxy
        import json
        oauth1_path = os.path.join(LOCAL_TOKEN_DIR, "oauth1_token.json")
        oauth2_path = os.path.join(LOCAL_TOKEN_DIR, "oauth2_token.json")

        with open(oauth1_path) as f:
            oauth1 = json.load(f)
        with open(oauth2_path) as f:
            oauth2 = json.load(f)

        payload = json.dumps({"oauth1_token": oauth1, "oauth2_token": oauth2})

        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no",
             "-p", HAOS_PORT, f"{HAOS_USER}@{HAOS_HOST}",
             f"curl -s -X POST -H 'Content-Type: application/json' "
             f"-d '{payload}' "
             f"'http://ecfdb23d-garmincoach:3000/api/garmin/auth-import'"],
            capture_output=True, text=True
        )

        if result.stdout:
            print(f"  API response: {result.stdout}")

        # Fallback: also try direct auth server endpoint
        result2 = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no",
             "-p", HAOS_PORT, f"{HAOS_USER}@{HAOS_HOST}",
             f"curl -s -X POST -H 'Content-Type: application/json' "
             f"-d '{payload}' "
             f"'http://ecfdb23d-garmincoach:8099/auth/import-tokens'"],
            capture_output=True, text=True
        )

        if result2.stdout and "success" in result2.stdout:
            print(f"  ✓ {result2.stdout.strip()}")
            print("\n✓ Tokens imported into addon!")
        else:
            print(f"  Direct API: {result2.stdout or result2.stderr}")
            print("\n⚠ Auto-import may have failed. Tokens are on HAOS at /tmp/.")
            print("  Restart the addon to try again, or rebuild with token import support.")

    except subprocess.CalledProcessError as exc:
        print(f"\n✗ Deploy failed: {exc.stderr}")
        print("  Tokens saved locally at:", LOCAL_TOKEN_DIR)


if __name__ == "__main__":
    main()
