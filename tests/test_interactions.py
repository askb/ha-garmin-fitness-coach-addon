#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
"""Tests for interactions.py: the Stress Board quick-add JSONL store.

Run: python -m pytest tests/test_interactions.py
"""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parents[1] / "pulsecoach" / "rootfs"
           / "app" / "scripts" / "interactions.py")
_spec = importlib.util.spec_from_file_location("interactions", _SCRIPT)
ix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ix)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point the module at a per-test JSONL path."""
    path = tmp_path / "interactions.jsonl"
    monkeypatch.setattr(ix, "INTERACTIONS_PATH", str(path))
    return path


def test_add_returns_record_with_id_and_defaults(store):
    rec = ix.add_interaction("Alice", 30)
    assert rec["person"] == "Alice"
    assert rec["minutes"] == 30
    assert rec["id"]
    # end defaults to roughly now (UTC)
    end = datetime.fromisoformat(rec["end"])
    assert abs((datetime.now(timezone.utc) - end).total_seconds()) < 5


def test_add_appends_one_json_line_compatible_with_meeting_stress(store):
    ix.add_interaction("Bob", 45, "2026-07-11T02:00:00+00:00")
    lines = store.read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    # exactly the shape meeting-stress.py load_interactions() consumes
    assert rec["person"] == "Bob"
    assert rec["minutes"] == 45
    assert datetime.fromisoformat(rec["end"])


def test_add_validates_person(store):
    for bad in ("", "   ", "x" * 201):
        with pytest.raises(ix.InteractionError):
            ix.add_interaction(bad, 30)


def test_add_validates_minutes(store):
    for bad in (0, -5, 1441, "abc", None):
        with pytest.raises(ix.InteractionError):
            ix.add_interaction("Alice", bad)


def test_add_validates_end_timestamp(store):
    with pytest.raises(ix.InteractionError):
        ix.add_interaction("Alice", 30, "not-a-date")
    with pytest.raises(ix.InteractionError):
        # far future ends are user error, reject > 1 day ahead
        future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        ix.add_interaction("Alice", 30, future)


def test_list_newest_first_with_ids(store):
    ix.add_interaction("Alice", 15, "2026-07-11T01:00:00+00:00")
    ix.add_interaction("Bob", 30, "2026-07-11T02:00:00+00:00")
    entries = ix.list_interactions()
    assert [e["person"] for e in entries] == ["Bob", "Alice"]
    assert all(e["id"] for e in entries)
    assert len({e["id"] for e in entries}) == 2


def test_list_skips_malformed_lines(store):
    store.write_text('not json\n{"person":"Ok","minutes":30,'
                     '"end":"2026-07-11T02:00:00+00:00"}\n{"minutes":5}\n')
    entries = ix.list_interactions()
    assert [e["person"] for e in entries] == ["Ok"]


def test_list_respects_limit(store):
    for i in range(30):
        ix.add_interaction(f"p{i}", 10, f"2026-07-10T{i % 24:02d}:00:00+00:00")
    assert len(ix.list_interactions(limit=5)) == 5
    assert len(ix.list_interactions()) <= 20


def test_list_missing_file_is_empty(store):
    assert ix.list_interactions() == []


def test_list_zero_or_negative_limit_is_empty(store):
    ix.add_interaction("Alice", 15)
    assert ix.list_interactions(limit=0) == []
    assert ix.list_interactions(limit=-3) == []


def test_list_skips_nonfinite_minutes(store):
    """json.loads accepts NaN/Infinity literals; they must not poison the
    listing (int(NaN) raises)."""
    store.write_text(
        '{"person":"A","minutes":NaN,"end":"2026-07-11T02:00:00+00:00"}\n'
        '{"person":"B","minutes":Infinity,"end":"2026-07-11T02:00:00+00:00"}\n'
        '{"person":"Ok","minutes":30,"end":"2026-07-11T02:00:00+00:00"}\n')
    entries = ix.list_interactions()
    assert [e["person"] for e in entries] == ["Ok"]


def test_list_treats_naive_end_as_utc(store):
    """Hand-written lines without an offset score as UTC in meeting-stress;
    the listing must agree."""
    store.write_text('{"person":"Ok","minutes":30,'
                     '"end":"2026-07-11T02:00:00"}\n')
    entries = ix.list_interactions()
    end = datetime.fromisoformat(entries[0]["end"])
    assert end.tzinfo is not None
    assert end.utcoffset().total_seconds() == 0


def test_delete_removes_only_matching_line(store):
    ix.add_interaction("Alice", 15, "2026-07-11T01:00:00+00:00")
    keep = ix.add_interaction("Bob", 30, "2026-07-11T02:00:00+00:00")
    victim = ix.list_interactions()[1]  # Alice
    assert ix.delete_interaction(victim["id"]) is True
    entries = ix.list_interactions()
    assert [e["person"] for e in entries] == ["Bob"]
    assert entries[0]["id"] == keep["id"]


def test_delete_unknown_id_returns_false(store):
    ix.add_interaction("Alice", 15)
    assert ix.delete_interaction("deadbeef0000") is False
    assert len(ix.list_interactions()) == 1


def test_delete_preserves_malformed_lines(store):
    """Hand-written HA shell_command lines must survive a UI delete."""
    store.write_text("# manual note, not json\n")
    rec = ix.add_interaction("Alice", 15)
    assert ix.delete_interaction(rec["id"]) is True
    assert store.read_text().startswith("# manual note")


def test_identical_adds_get_distinct_ids(store):
    a = ix.add_interaction("Alice", 30, "2026-07-11T02:00:00+00:00")
    b = ix.add_interaction("Alice", 30, "2026-07-11T02:00:00+00:00")
    assert a["id"] != b["id"]
    assert ix.delete_interaction(a["id"]) is True
    assert len(ix.list_interactions()) == 1
