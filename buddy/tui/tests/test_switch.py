"""Tests for /buddy switch (buddy/switch.py).

Covers: matching by name and species_id, ambiguous queries, missing
target, already-active no-op, and the happy path (file rewritten with
new active_id).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUDDY = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _BUDDY not in sys.path:
    sys.path.insert(0, _BUDDY)

import switch  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_progression(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(switch, "PROGRESSION", tmp_path / "progression.json")
    yield


def _seed(collection: dict) -> None:
    switch.PROGRESSION.write_text(json.dumps(collection))


def _two_buddies() -> dict:
    return {
        "active_id": "slime",
        "buddies": {
            "slime": {"species_id": "slime", "species_name": "Slime", "name": "blob"},
            "ember": {"species_id": "ember", "species_name": "Ember", "name": None},
        },
        "hatches_performed": 2, "shards": 0,
    }


# ─── happy paths ────────────────────────────────────────────────────────────


def test_switch_by_custom_name(monkeypatch, capsys) -> None:
    _seed(_two_buddies())
    monkeypatch.setattr(sys, "argv", ["switch", "blob"])
    # Already active, but this test is about matching by name. Add another
    # named buddy to switch TO.
    collection = _two_buddies()
    collection["buddies"]["ember"]["name"] = "flicker"
    _seed(collection)
    monkeypatch.setattr(sys, "argv", ["switch", "flicker"])
    assert switch.main() == 0
    saved = json.loads(switch.PROGRESSION.read_text())
    assert saved["active_id"] == "ember"
    assert "Switched to flicker" in capsys.readouterr().out


def test_switch_by_species_id(monkeypatch, capsys) -> None:
    _seed(_two_buddies())
    monkeypatch.setattr(sys, "argv", ["switch", "ember"])
    assert switch.main() == 0
    saved = json.loads(switch.PROGRESSION.read_text())
    assert saved["active_id"] == "ember"


def test_switch_is_case_insensitive(monkeypatch) -> None:
    _seed(_two_buddies())
    monkeypatch.setattr(sys, "argv", ["switch", "EMBER"])
    assert switch.main() == 0
    saved = json.loads(switch.PROGRESSION.read_text())
    assert saved["active_id"] == "ember"


# ─── error paths ────────────────────────────────────────────────────────────


def test_switch_without_args_shows_help(monkeypatch, capsys) -> None:
    _seed(_two_buddies())
    monkeypatch.setattr(sys, "argv", ["switch"])
    assert switch.main() == 1
    out = capsys.readouterr().out
    assert "Usage" in out
    # Help should include the command reference so users don't dig.
    assert "claude-buddy" in out


def test_switch_help_flag_exits_zero(monkeypatch) -> None:
    _seed(_two_buddies())
    monkeypatch.setattr(sys, "argv", ["switch", "--help"])
    assert switch.main() == 0


def test_switch_unknown_name_shows_collection(monkeypatch, capsys) -> None:
    _seed(_two_buddies())
    monkeypatch.setattr(sys, "argv", ["switch", "moonwyrm"])
    assert switch.main() == 1
    out = capsys.readouterr().out
    assert "No buddy matches 'moonwyrm'" in out
    # Status block visible so user can see their actual collection.
    assert "Collection:" in out


def test_switch_no_collection_file(monkeypatch, capsys) -> None:
    # PROGRESSION doesn't exist.
    monkeypatch.setattr(sys, "argv", ["switch", "anything"])
    assert switch.main() == 1
    out = capsys.readouterr().out
    assert "don't have any buddies" in out


def test_switch_ambiguous_name_lists_candidates(monkeypatch, capsys) -> None:
    # Two buddies with the SAME custom name (users can do this today).
    collection = {
        "active_id": "slime",
        "buddies": {
            "slime": {"species_id": "slime", "name": "bubble"},
            "ember": {"species_id": "ember", "name": "bubble"},
        },
        "hatches_performed": 2, "shards": 0,
    }
    _seed(collection)
    monkeypatch.setattr(sys, "argv", ["switch", "bubble"])
    assert switch.main() == 1
    out = capsys.readouterr().out
    assert "Ambiguous" in out
    assert "slime" in out
    assert "ember" in out


def test_switch_to_active_is_noop(monkeypatch, capsys) -> None:
    _seed(_two_buddies())
    monkeypatch.setattr(sys, "argv", ["switch", "slime"])
    assert switch.main() == 0
    out = capsys.readouterr().out
    assert "already active" in out
    # File shouldn't change.
    saved = json.loads(switch.PROGRESSION.read_text())
    assert saved["active_id"] == "slime"
