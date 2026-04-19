"""State adapter — single source of truth for habitat widgets.

Reads ~/.claude/buddy/{state,progression}.json and produces a BuddyView: a
frozen snapshot of everything the habitat widgets need. Widgets subscribe to
BuddyView updates rather than reading the JSON themselves, so we poll once.

Reuses buddy/state.py (derive_mood) and buddy/species.py (find_species) —
the Textual UI is a view layer over the existing model.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Reach back to buddy/*.py (flat layout, matches project convention).
_HERE = Path(__file__).resolve().parent
_BUDDY = _HERE.parent
sys.path.insert(0, str(_BUDDY))
from state import derive_mood  # noqa: E402
from collection import active_buddy, migrate  # noqa: E402

# Default file paths honour BUDDY_STATE_DIR so sim-test runs redirect
# automatically. Overridable via args (used by pytest).
from state import STATE as _DEFAULT_STATE, PROGRESSION as _DEFAULT_PROGRESSION  # noqa: E402

_SPEECH_TTL = 12  # seconds; matches buddy.py
_ACTIVITY_TAU = 30  # seconds; decay time constant for activity_rate


@dataclass(frozen=True)
class BuddyView:
    """Everything the habitat widgets need in one immutable snapshot."""

    # Identity
    has_buddy: bool
    species_id: Optional[str]
    name: Optional[str]
    rarity: Optional[str]
    signature_skill: Optional[str]

    # State
    mood: str                  # idle | attentive | watching | sleeping
    current_tool: Optional[str]
    speech: Optional[str]      # recent chirp, or None if stale
    activity_rate: float       # 0..1, exponential decay from last event

    # Progression
    total_prompts: int
    total_tools: int
    xp: int
    level: int
    time_with_buddy_s: int

    # Raw progression (for widgets that want more)
    skills: dict               # {skill_name: score 0-100}


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def read_view(
    state_path: Path = _DEFAULT_STATE,
    progression_path: Path = _DEFAULT_PROGRESSION,
    now: Optional[float] = None,
) -> BuddyView:
    """Read both files and compose a BuddyView."""
    now = time.time() if now is None else now
    state = _read_json(Path(state_path))
    raw_prog = _read_json(Path(progression_path))
    # Always migrate — handles both collection shape and legacy single-buddy.
    # active_buddy() returns the flat dict the rest of this function expects.
    prog = active_buddy(migrate(raw_prog)) or {}

    has_buddy = bool(prog.get("species_id"))

    # Mood: reuse the existing derivation logic so curses + TUI agree.
    mood = derive_mood(state) if state else "idle"

    # Speech: drop if older than TTL.
    speech = state.get("speech")
    speech_ts = state.get("speech_ts", 0)
    if not speech or (now - speech_ts) >= _SPEECH_TTL:
        speech = None

    # Activity: exponential decay from last event.
    last_ts = state.get("last_event_ts", 0)
    age = max(0.0, now - last_ts) if last_ts else float("inf")
    activity_rate = math.exp(-age / _ACTIVITY_TAU) if last_ts else 0.0

    total_prompts = int(prog.get("total_prompts", 0))
    total_tools = int(prog.get("total_tools", 0))
    xp = total_prompts + total_tools // 3
    level = int(math.sqrt(xp / 10)) if xp > 0 else 0

    first_seen = prog.get("first_seen_ts", 0)
    time_with_buddy_s = max(0, int(now - first_seen)) if first_seen else 0

    return BuddyView(
        has_buddy=has_buddy,
        species_id=prog.get("species_id"),
        name=prog.get("name"),
        rarity=prog.get("rarity"),
        signature_skill=prog.get("signature_skill"),
        mood=mood,
        current_tool=state.get("current_tool"),
        speech=speech,
        activity_rate=activity_rate,
        total_prompts=total_prompts,
        total_tools=total_tools,
        xp=xp,
        level=level,
        time_with_buddy_s=time_with_buddy_s,
        skills=dict(prog.get("skills", {})),
    )
