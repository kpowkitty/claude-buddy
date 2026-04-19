"""Tests for the Ctrl+P pet reaction.

Three layers covered here:

1. `state.derive_mood` → returns 'petted' while `petted_until > now`, falls
   through to the normal mood chain after the deadline passes.
2. `sprites.frames_for` → 'petted' mood produces closed eyes + (best-effort)
   smile, identical frame A and B so the buddy reads as "still, content".
3. `app.action_pet` → writes `petted_until`, `speech="prrr"`, and bumps the
   active buddy's `pets_received` counter.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

import app as _app_mod
from app import BuddyApp

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUDDY = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _BUDDY not in sys.path:
    sys.path.insert(0, _BUDDY)

from sprites import frames_for  # noqa: E402
from state import derive_mood  # noqa: E402


# ─── derive_mood ─────────────────────────────────────────────────────────────


def test_derive_mood_returns_petted_while_within_window() -> None:
    state = {"petted_until": time.time() + 2}
    assert derive_mood(state) == "petted"


def test_derive_mood_drops_petted_after_deadline() -> None:
    state = {"petted_until": time.time() - 0.1}
    # Without a fresh event, we fall back to idle / sleeping.
    assert derive_mood(state) in {"idle", "sleeping"}


def test_derive_mood_petted_beats_watching() -> None:
    """Petting mid-tool-use still wins — the response to a user gesture
    should take precedence over an ongoing watch."""
    now = time.time()
    state = {"petted_until": now + 2, "watching_until": now + 5}
    assert derive_mood(state) == "petted"


# ─── sprite frames ───────────────────────────────────────────────────────────


def test_petted_frames_leave_kitsune_eyes_and_smile_the_mouth() -> None:
    """Kitsune's `^.^` eyes stay happy on petting. The `.` between them
    (the mouth) swaps to `‿` — final look is `^‿^`. The `> v <` paws-
    holding pose stays intact."""
    a, _ = frames_for("kitsune", "petted")
    joined = "\n".join(a)
    assert "^‿^" in joined, f"expected ^‿^ face, got:\n{joined}"
    # The original `^.^` is replaced (by the mouth swap, not an eye swap).
    assert "^.^" not in joined
    # Paws (`> v <`) should be untouched — they're not a mouth.
    assert "> v <" in joined


def test_petted_frames_close_eyes_on_round_eyed_species() -> None:
    """Slime has `o`-style eyes; petted should swap them to `-`."""
    a, _ = frames_for("slime", "petted")
    joined = "\n".join(a)
    # No raw `o` eye left in the sprite body after closing.
    assert "-" in joined
    # And there shouldn't be a lowercase-o that's part of the eye pattern.
    # (The word "o" could appear in an `_add_overlay` line, but petted doesn't
    # add overlays, so the sprite is just the base art with eye subs.)


def test_petted_does_not_add_sparkle_or_zzz_overlay() -> None:
    a, _ = frames_for("slime", "petted")
    joined = "\n".join(a)
    assert "zZz" not in joined
    assert "*" not in joined


# ─── action_pet end-to-end ──────────────────────────────────────────────────


def _seed_progression(tmp_path: Path) -> Path:
    prog = tmp_path / "progression.json"
    prog.write_text(json.dumps({
        "active_id": "kitsune",
        "buddies": {"kitsune": {
            "species_id": "kitsune", "species_name": "Kitsune",
            "name": "quine", "pets_received": 0,
        }},
        "hatches_performed": 1, "shards": 0,
    }))
    return prog


@pytest.mark.asyncio
async def test_action_pet_writes_petted_until_and_prrr(monkeypatch, tmp_path) -> None:
    prog_path = _seed_progression(tmp_path)
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    monkeypatch.setattr(_app_mod, "PROGRESSION", prog_path)
    monkeypatch.setattr(_app_mod, "STATE", state_path)

    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        before = time.time()
        await pilot.press("f1")
        await pilot.pause(0.1)
        after = time.time()

        state = json.loads(state_path.read_text())
        assert state.get("speech") == "prrr"
        # Window extends PET_REACTION_SECONDS beyond the call.
        assert state.get("petted_until", 0) >= before + app.PET_REACTION_SECONDS - 0.2
        assert state.get("petted_until", 0) <= after + app.PET_REACTION_SECONDS + 0.2

        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_action_pet_still_bumps_pets_received(monkeypatch, tmp_path) -> None:
    prog_path = _seed_progression(tmp_path)
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    monkeypatch.setattr(_app_mod, "PROGRESSION", prog_path)
    monkeypatch.setattr(_app_mod, "STATE", state_path)

    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        await pilot.press("f1")
        await pilot.pause(0.1)
        data = json.loads(prog_path.read_text())
        assert data["buddies"]["kitsune"]["pets_received"] == 1
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)
