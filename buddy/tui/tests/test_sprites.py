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


# ─── slime jiggle ────────────────────────────────────────────────────────────


def test_slime_has_tail_b() -> None:
    _, species = find_species("slime")
    assert species is not None
    assert "tail_b" in species
    # Row 4 of the base art holds the underside tildes; tail_b shifts them.
    assert 4 in species["tail_b"]


def test_slime_frame_b_underside_is_shifted() -> None:
    """Slime's idle animation should alternate the underside tilde pattern:
    frame A has `/~ ~ ~ ~ ~\\`, frame B has `/ ~ ~ ~ ~ \\`."""
    a, b = frames_for("slime", "idle")
    # Row 4 is the underside.
    assert "~" in a[4]
    assert "~" in b[4]
    assert a[4] != b[4], "slime frame B row 4 should differ from frame A"


def test_unknown_species_returns_fallback() -> None:
    a, b = frames_for("not_a_real_species", "idle")
    assert a == ["?"]
    assert b == ["?"]
