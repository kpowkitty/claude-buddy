"""Tests for sprite frame generation — specifically the composable tail_b
overlay that lets any species opt into a wag animation without touching
sprites.py.
"""
from __future__ import annotations

import os
import sys

# frames_for lives in buddy/sprites.py (one dir up from buddy/tui).
_HERE = os.path.dirname(os.path.abspath(__file__))
_BUDDY = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _BUDDY not in sys.path:
    sys.path.insert(0, _BUDDY)

from sprites import frames_for  # noqa: E402
from species import find_species  # noqa: E402


# ─── kitsune has tail_b and animates ─────────────────────────────────────────


def test_kitsune_idle_frames_differ_via_tail_b() -> None:
    """Frame B should differ from frame A for kitsune on every mood,
    including moods that don't mutate eyes (e.g., watching)."""
    a, b = frames_for("kitsune", "idle")
    assert a != b, "kitsune idle frames identical — wag not applied"


def test_kitsune_watching_frames_differ_via_tail_b() -> None:
    """'watching' mood doesn't alter eyes between frames, so without a
    tail wag the two frames would be identical. tail_b is the only thing
    producing motion here."""
    a, b = frames_for("kitsune", "watching")
    assert a != b, "kitsune watching frames identical — tail_b not applied"


def test_kitsune_sleeping_frames_still_differ_with_overlay() -> None:
    """tail_b indices are keyed against base art; _add_overlay prepends a
    row. The implementation must apply tail_b BEFORE the overlay so indices
    remain valid."""
    a, b = frames_for("kitsune", "sleeping")
    assert a != b, "kitsune sleeping frames identical — tail_b index misaligned?"


def test_kitsune_tail_b_actually_changes_expected_rows() -> None:
    """Frame B's row 1..4 should match the declared tail_b rows (the
    frames also pass through eye substitution, so we can't compare the
    whole line literally — just check for the distinguishing tail glyphs)."""
    _, species = find_species("kitsune")
    assert species is not None
    tail_b = species.get("tail_b")
    assert tail_b is not None, "fixture expects kitsune to declare tail_b"
    _, frame_b = frames_for("kitsune", "idle")
    # Row 1 in base ends with `  /` (forward slash). In wag it ends with `  \`.
    assert frame_b[1].rstrip().endswith("\\"), (
        f"expected row 1 wag to end with backslash, got {frame_b[1]!r}"
    )


# ─── species without tail_b are unchanged ────────────────────────────────────


def test_slime_has_no_tail_b() -> None:
    _, species = find_species("slime")
    assert species is not None
    assert "tail_b" not in species


def test_slime_frames_only_differ_by_blink() -> None:
    """Species without tail_b should animate exactly as before — idle's
    frame B is just the eye-blink variant, nothing more."""
    a, b = frames_for("slime", "idle")
    # Both frames are the same height and width.
    assert len(a) == len(b)
    # Difference must be limited to eye characters (o/O → -), not tail glyphs.
    for row_a, row_b in zip(a, b):
        diffs = [(i, ca, cb) for i, (ca, cb) in enumerate(zip(row_a, row_b)) if ca != cb]
        for _, ca, cb in diffs:
            assert ca in "oO" and cb == "-", (
                f"slime frame differs by non-blink glyph: {ca!r} → {cb!r}"
            )


def test_unknown_species_returns_fallback() -> None:
    a, b = frames_for("not_a_real_species", "idle")
    assert a == ["?"]
    assert b == ["?"]
