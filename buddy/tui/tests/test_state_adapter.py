"""Tests for state_adapter.

The adapter reads ~/.claude/buddy/{state,progression}.json and derives a
`BuddyView` — a frozen snapshot of everything the habitat widgets need.
Widgets never read JSON directly; they subscribe to BuddyView updates.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from state_adapter import BuddyView, read_view


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data))


# ─── no buddy hatched ─────────────────────────────────────────────────────


def test_no_progression_file(tmp_path: Path) -> None:
    view = read_view(tmp_path / "state.json", tmp_path / "progression.json")
    assert view.has_buddy is False
    assert view.species_id is None
    assert view.name is None


def test_progression_without_species_id(tmp_path: Path) -> None:
    _write(tmp_path / "progression.json", {"name": "???"})
    view = read_view(tmp_path / "state.json", tmp_path / "progression.json")
    assert view.has_buddy is False


# ─── basic view ───────────────────────────────────────────────────────────


def test_hatched_buddy_populates_view(tmp_path: Path) -> None:
    _write(tmp_path / "progression.json", {
        "species_id": "pebble",
        "name": "Rocky",
        "rarity": "common",
        "signature_skill": "patience",
        "total_prompts": 20,
        "total_tools": 30,
        "first_seen_ts": time.time() - 3600,
    })
    _write(tmp_path / "state.json", {
        "last_event": "prompt",
        "last_event_ts": time.time(),
    })
    view = read_view(tmp_path / "state.json", tmp_path / "progression.json")
    assert view.has_buddy is True
    assert view.species_id == "pebble"
    assert view.name == "Rocky"
    assert view.rarity == "common"


# ─── mood derivation reuses state.derive_mood ─────────────────────────────


def test_mood_attentive_after_recent_prompt(tmp_path: Path) -> None:
    _write(tmp_path / "progression.json", {"species_id": "pebble"})
    _write(tmp_path / "state.json", {
        "last_event": "prompt",
        "last_event_ts": time.time(),  # <3s ago
    })
    view = read_view(tmp_path / "state.json", tmp_path / "progression.json")
    assert view.mood == "attentive"


def test_mood_sleeping_after_long_idle(tmp_path: Path) -> None:
    _write(tmp_path / "progression.json", {"species_id": "pebble"})
    _write(tmp_path / "state.json", {
        "last_event": "stop",
        "last_event_ts": time.time() - 200,  # >120s ago
    })
    view = read_view(tmp_path / "state.json", tmp_path / "progression.json")
    assert view.mood == "sleeping"


def test_mood_watching_when_tool_active(tmp_path: Path) -> None:
    _write(tmp_path / "progression.json", {"species_id": "pebble"})
    _write(tmp_path / "state.json", {
        "last_event": "pre_tool",
        "last_event_ts": time.time(),
        "watching_until": time.time() + 60,
    })
    view = read_view(tmp_path / "state.json", tmp_path / "progression.json")
    assert view.mood == "watching"


# ─── XP + level ───────────────────────────────────────────────────────────


def test_xp_computed_from_counters(tmp_path: Path) -> None:
    _write(tmp_path / "progression.json", {
        "species_id": "pebble",
        "total_prompts": 30,
        "total_tools": 15,
    })
    _write(tmp_path / "state.json", {})
    view = read_view(tmp_path / "state.json", tmp_path / "progression.json")
    # xp = total_prompts + total_tools // 3  =  30 + 5 = 35
    assert view.xp == 35


def test_level_computed_from_xp(tmp_path: Path) -> None:
    _write(tmp_path / "progression.json", {
        "species_id": "pebble",
        "total_prompts": 40,  # xp = 40
    })
    _write(tmp_path / "state.json", {})
    view = read_view(tmp_path / "state.json", tmp_path / "progression.json")
    # level = int(sqrt(xp / 10)) = int(sqrt(4)) = 2
    assert view.level == 2


def test_level_zero_when_no_xp(tmp_path: Path) -> None:
    _write(tmp_path / "progression.json", {"species_id": "pebble"})
    _write(tmp_path / "state.json", {})
    view = read_view(tmp_path / "state.json", tmp_path / "progression.json")
    assert view.xp == 0
    assert view.level == 0


# ─── time-with-buddy ──────────────────────────────────────────────────────


def test_time_with_buddy_seconds(tmp_path: Path) -> None:
    seen = time.time() - 3665  # 1h 1m 5s ago
    _write(tmp_path / "progression.json", {
        "species_id": "pebble",
        "first_seen_ts": seen,
    })
    _write(tmp_path / "state.json", {})
    view = read_view(tmp_path / "state.json", tmp_path / "progression.json")
    # Should be ~3665 seconds, give or take a couple due to clock drift in test.
    assert 3660 <= view.time_with_buddy_s <= 3670


def test_time_with_buddy_missing_first_seen_is_zero(tmp_path: Path) -> None:
    _write(tmp_path / "progression.json", {"species_id": "pebble"})
    _write(tmp_path / "state.json", {})
    view = read_view(tmp_path / "state.json", tmp_path / "progression.json")
    assert view.time_with_buddy_s == 0


# ─── activity rate ────────────────────────────────────────────────────────


def test_activity_rate_high_for_recent_activity(tmp_path: Path) -> None:
    _write(tmp_path / "progression.json", {"species_id": "pebble"})
    _write(tmp_path / "state.json", {
        "last_event": "prompt",
        "last_event_ts": time.time() - 5,  # very recent
    })
    view = read_view(tmp_path / "state.json", tmp_path / "progression.json")
    assert view.activity_rate > 0.5


def test_activity_rate_low_when_idle(tmp_path: Path) -> None:
    _write(tmp_path / "progression.json", {"species_id": "pebble"})
    _write(tmp_path / "state.json", {
        "last_event": "stop",
        "last_event_ts": time.time() - 120,  # 2 min ago
    })
    view = read_view(tmp_path / "state.json", tmp_path / "progression.json")
    assert view.activity_rate < 0.2


# ─── speech passthrough ───────────────────────────────────────────────────


def test_recent_speech_surfaces(tmp_path: Path) -> None:
    _write(tmp_path / "progression.json", {"species_id": "pebble"})
    _write(tmp_path / "state.json", {
        "speech": "hi!",
        "speech_ts": time.time(),
    })
    view = read_view(tmp_path / "state.json", tmp_path / "progression.json")
    assert view.speech == "hi!"


def test_stale_speech_is_none(tmp_path: Path) -> None:
    _write(tmp_path / "progression.json", {"species_id": "pebble"})
    _write(tmp_path / "state.json", {
        "speech": "hi!",
        "speech_ts": time.time() - 60,  # > 12s TTL
    })
    view = read_view(tmp_path / "state.json", tmp_path / "progression.json")
    assert view.speech is None


# ─── view immutability ────────────────────────────────────────────────────


def test_view_is_frozen(tmp_path: Path) -> None:
    _write(tmp_path / "progression.json", {"species_id": "pebble"})
    _write(tmp_path / "state.json", {})
    view = read_view(tmp_path / "state.json", tmp_path / "progression.json")
    with pytest.raises((AttributeError, Exception)):
        view.xp = 999  # frozen dataclass
