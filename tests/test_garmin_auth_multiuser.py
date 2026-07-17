# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Integration tests for multi-tenant scoping in garmin-auth-server.py.

Loads the Flask app with garminconnect mocked and TOKEN_DIR redirected to a
tmp dir, then verifies per-user token isolation, per-user MFA state, and that
sync is launched with per-user env — while an addon-style request (no user
header) keeps using the shared token dir (backward compatible).
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

# The integration suite imports the Flask auth server, which needs flask +
# garminconnect (Docker runtime deps). Where they're absent (minimal CI), skip
# the whole module — the flask-free helper unit tests still cover the core
# logic. Locally / in the image these run in full.
pytest.importorskip("flask")
pytest.importorskip("garminconnect")

_SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / "pulsecoach"
    / "rootfs"
    / "app"
    / "scripts"
)
USER_HEADER = "X-PulseCoach-User"

# Make sibling imports (gcal, interactions, helper modules) resolvable once,
# without mutating sys.path inside the fixture on every test.
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


class _FakeGarth:
    def __init__(self, marker):
        self._marker = marker

    def dump(self, token_dir):
        os.makedirs(token_dir, exist_ok=True)
        # Emulate garth writing the native token file.
        with open(os.path.join(token_dir, "garmin_tokens.json"), "w") as f:
            json.dump({"marker": self._marker}, f)


class _FakeGarmin:
    """Stand-in for garminconnect.Garmin.

    - Constructed with (email) for _load_client → login(tokenstore=...) is a
      no-op success.
    - Constructed with (email, password, ...) for the login endpoint →
      login() returns ("a","b") success, unless the password is "MFA" in which
      case it returns ("needs_mfa","state").
    """

    def __init__(self, email=None, password=None, **kwargs):
        self._email = email
        self._password = password
        self.garth = _FakeGarth(email or "loaded")

    def login(self, tokenstore=None):
        if tokenstore is not None:
            return None  # _load_client path: token load succeeds
        if self._password == "MFA":
            return ("needs_mfa", "client-state-token")
        return ("oauth1", "oauth2")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "gas_under_test", _SCRIPTS / "garmin-auth-server.py"
    )
    gas = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gas)

    # Redirect token storage to a writable tmp dir and mock Garmin.
    monkeypatch.setattr(gas, "TOKEN_DIR", str(tmp_path / "garmin-tokens"))
    monkeypatch.setattr(gas, "Garmin", _FakeGarmin)
    gas.app.config.update(TESTING=True)
    return gas, gas.app.test_client()


def _user_dir(gas, user_id):
    return gas.user_token_dir(gas.TOKEN_DIR, user_id)


# ── import-tokens isolation ─────────────────────────────────────────────────

def test_import_tokens_single_user_uses_base_dir(client):
    gas, c = client
    resp = c.post("/auth/import-tokens", json={
        "oauth1_token": {"a": 1}, "oauth2_token": {"b": 2},
    })
    assert resp.status_code == 200
    # Written directly under the base dir (addon behavior).
    assert os.path.exists(os.path.join(gas.TOKEN_DIR, "oauth1_token.json"))
    assert not os.path.isdir(os.path.join(gas.TOKEN_DIR, "users"))


def test_import_tokens_per_user_is_isolated(client):
    gas, c = client
    for user in ("alice", "bob"):
        r = c.post(
            "/auth/import-tokens",
            json={"oauth1_token": {"u": user}, "oauth2_token": {"u": user}},
            headers={USER_HEADER: user},
        )
        assert r.status_code == 200

    alice_dir = _user_dir(gas, "alice")
    bob_dir = _user_dir(gas, "bob")
    assert alice_dir != bob_dir
    assert os.path.exists(os.path.join(alice_dir, "oauth1_token.json"))
    assert os.path.exists(os.path.join(bob_dir, "oauth1_token.json"))
    # Neither leaked into the shared base dir.
    assert not os.path.exists(os.path.join(gas.TOKEN_DIR, "oauth1_token.json"))
    # Alice's payload is not visible under bob's dir.
    with open(os.path.join(alice_dir, "oauth1_token.json")) as f:
        assert json.load(f) == {"u": "alice"}


# ── status isolation ────────────────────────────────────────────────────────

def test_status_reflects_only_that_users_tokens(client):
    gas, c = client
    # alice connects; bob does not.
    c.post("/auth/import-tokens",
           json={"oauth1_token": {"x": 1}, "oauth2_token": {"y": 2}},
           headers={USER_HEADER: "alice"})

    alice = c.get("/auth/status", headers={USER_HEADER: "alice"}).get_json()
    bob = c.get("/auth/status", headers={USER_HEADER: "bob"}).get_json()
    assert alice["connected"] is True
    assert bob["connected"] is False


# ── login → MFA state is per-user ───────────────────────────────────────────

def test_login_success_saves_tokens_for_user(client):
    gas, c = client
    r = c.post("/auth/login",
               json={"email": "a@x.com", "password": "good"},
               headers={USER_HEADER: "alice"})
    body = r.get_json()
    assert body["success"] is True
    assert os.path.exists(
        os.path.join(_user_dir(gas, "alice"), "garmin_tokens.json"))


def test_pending_mfa_is_isolated_per_user(client):
    gas, c = client
    # alice triggers MFA (password "MFA" → needs_mfa); bob does not log in.
    r = c.post("/auth/login",
               json={"email": "a@x.com", "password": "MFA"},
               headers={USER_HEADER: "alice"})
    assert r.get_json()["needsMfa"] is True
    assert gas._mfa_store.has("alice")
    assert not gas._mfa_store.has("bob")
    assert not gas._mfa_store.has(None)  # single-user slot untouched


# ── sync launches with per-user env ─────────────────────────────────────────

def test_sync_passes_per_user_env(client, monkeypatch):
    gas, c = client
    # Give alice tokens so the "connected" check passes.
    c.post("/auth/import-tokens",
           json={"oauth1_token": {"x": 1}, "oauth2_token": {"y": 2}},
           headers={USER_HEADER: "alice"})

    captured = {}

    class _FakePopen:
        def __init__(self, argv, env=None, stdout=None, stderr=None):
            captured["argv"] = argv
            captured["env"] = env

    import subprocess
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(gas, "SYNC_LOG_PATH", str(gas.TOKEN_DIR) + "-sync.log")
    monkeypatch.setattr(gas, "SYNC_LOG_PREV_PATH", str(gas.TOKEN_DIR) + "-sync.log.1")

    r = c.post("/auth/sync", headers={USER_HEADER: "alice"})
    assert r.status_code == 200
    assert captured["env"]["GARMIN_USER_ID"] == "alice"
    assert captured["env"]["GARMIN_TOKEN_DIR"] == _user_dir(gas, "alice")


def test_sync_single_user_uses_base_dir_and_no_user_id(client, monkeypatch):
    gas, c = client
    c.post("/auth/import-tokens",
           json={"oauth1_token": {"x": 1}, "oauth2_token": {"y": 2}})

    captured = {}

    class _FakePopen:
        def __init__(self, argv, env=None, stdout=None, stderr=None):
            captured["env"] = env

    import subprocess
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(gas, "SYNC_LOG_PATH", str(gas.TOKEN_DIR) + "-sync.log")
    monkeypatch.setattr(gas, "SYNC_LOG_PREV_PATH", str(gas.TOKEN_DIR) + "-sync.log.1")

    r = c.post("/auth/sync")
    assert r.status_code == 200
    # Addon mode: token dir is the base, and no per-user id is forced.
    assert captured["env"]["GARMIN_TOKEN_DIR"] == gas.TOKEN_DIR
    assert "GARMIN_USER_ID" not in captured["env"]


# ── logout only removes that user's tokens ──────────────────────────────────

def test_logout_removes_only_that_user(client):
    gas, c = client
    for user in ("alice", "bob"):
        c.post("/auth/import-tokens",
               json={"oauth1_token": {"u": user}, "oauth2_token": {"u": user}},
               headers={USER_HEADER: user})

    c.post("/auth/logout", headers={USER_HEADER: "alice"})
    assert not os.path.exists(_user_dir(gas, "alice"))
    assert os.path.exists(_user_dir(gas, "bob"))


# ── sync log is per-user (no cross-user leakage) ────────────────────────────

def test_sync_log_is_isolated_per_user(client, monkeypatch):
    gas, c = client
    for user in ("alice", "bob"):
        c.post("/auth/import-tokens",
               json={"oauth1_token": {"u": user}, "oauth2_token": {"u": user}},
               headers={USER_HEADER: user})

    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)

    # alice triggers a sync → her log gets a header line written.
    c.post("/auth/sync", headers={USER_HEADER: "alice"})
    alice_log = c.get("/auth/sync-log", headers={USER_HEADER: "alice"}).get_json()
    bob_log = c.get("/auth/sync-log", headers={USER_HEADER: "bob"}).get_json()

    assert alice_log["available"] is True
    # bob never synced → cannot see alice's log.
    assert bob_log["available"] is False


# ── credential dir hardening ────────────────────────────────────────────────

def test_import_tokens_refuses_symlinked_users_dir(client, tmp_path):
    gas, c = client
    # Pre-plant TOKEN_DIR/users as a symlink pointing outside the base.
    outside = tmp_path / "evil"
    outside.mkdir()
    users_link = os.path.join(gas.TOKEN_DIR, "users")
    os.makedirs(gas.TOKEN_DIR, exist_ok=True)
    os.symlink(str(outside), users_link)

    r = c.post(
        "/auth/import-tokens",
        json={"oauth1_token": {"x": 1}, "oauth2_token": {"y": 2}},
        headers={USER_HEADER: "alice"},
    )
    assert r.status_code == 500
    # Nothing was written into the attacker-controlled target.
    assert not any(outside.iterdir())


def test_sync_refuses_symlinked_users_dir(client, monkeypatch, tmp_path):
    gas, c = client
    outside = tmp_path / "evil2"
    outside.mkdir()
    os.makedirs(gas.TOKEN_DIR, exist_ok=True)
    os.symlink(str(outside), os.path.join(gas.TOKEN_DIR, "users"))

    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)

    r = c.post("/auth/sync", headers={USER_HEADER: "alice"})
    assert r.status_code == 500


def test_symlinked_per_user_dir_within_base_is_rejected(client):
    gas, c = client
    # bob connects normally.
    c.post("/auth/import-tokens",
           json={"oauth1_token": {"u": "bob"}, "oauth2_token": {"u": "bob"}},
           headers={USER_HEADER: "bob"})
    # Point alice's per-user dir at bob's — a symlink *within* TOKEN_DIR that
    # passes containment but would break isolation.
    alice_dir = _user_dir(gas, "alice")
    bob_dir = _user_dir(gas, "bob")
    os.makedirs(os.path.dirname(alice_dir), exist_ok=True)
    os.symlink(bob_dir, alice_dir)
    # alice must not read bob's tokens through the symlink.
    resp = c.get("/auth/status", headers={USER_HEADER: "alice"}).get_json()
    assert resp["connected"] is False



