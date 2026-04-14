"""Mood-specific frame generation from base species art.

Rather than hand-draw 11 species × 5 moods × 2 frames = 110 sprites, we transform
the base art in species.py by substituting eye/mouth glyphs and adding small
overlay characters (zZz, stars) near the top of the sprite.
"""
from __future__ import annotations

from species import find_species

# Mood → (frame_a_subs, frame_b_subs, top_overlay_a, top_overlay_b)
# Each sub is a list of (find, replace) pairs applied in order.

_EYE_PAIRS = ["o o", "O O", "o.o", "O.O", "o,o", "O,O", "O , O", "o   o", "O  O"]
_EYE_SINGLE = ["o", "O"]


def _sub_eyes(lines, new_eye_char):
    """Replace eye characters with given char, preserving spacing."""
    out = []
    for line in lines:
        new = line
        # Replace any lowercase/uppercase o/O that looks like an eye
        # (surrounded by non-letters). Simple heuristic: just swap o→X, O→X
        # where they appear inside parens-like structures.
        for ch in "oO":
            new = new.replace(ch, new_eye_char)
        out.append(new)
    return out


def _add_overlay(lines, overlay_line):
    """Prepend or replace top line with overlay (e.g., 'zZz' or '* . *')."""
    if not lines:
        return lines
    # Inject overlay into topmost line by centering it over the sprite width
    width = max(len(l) for l in lines)
    centered = overlay_line.center(width)
    # If topmost line is whitespace-only, replace; else prepend a new line
    top = lines[0]
    if top.strip() == "":
        return [centered] + lines[1:]
    return [centered] + lines


def _mouth_sub(lines, finds_and_replaces):
    out = []
    for line in lines:
        new = line
        for find, rep in finds_and_replaces:
            new = new.replace(find, rep)
        out.append(new)
    return out


def frames_for(species_id: str, mood: str):
    """Return a list of 2 frames (each a list of strings) for given species and mood."""
    _, species = find_species(species_id)
    if species is None:
        return [["?"], ["?"]]
    base = list(species["art"])

    if mood == "idle":
        # Frame A = base. Frame B = blink (eyes → -).
        f_a = list(base)
        f_b = _sub_eyes(base, "-")
        return [f_a, f_b]

    if mood == "attentive":
        # Wide eyes (O/0) and slight mouth twitch.
        f_a = _sub_eyes(base, "O")
        f_b = _sub_eyes(base, "0")
        return [f_a, f_b]

    if mood == "watching":
        # Fixated eyes (@).
        f_a = _sub_eyes(base, "@")
        f_b = _sub_eyes(base, "@")
        # Subtle motion: shift feet indicator if present
        return [f_a, f_b]

    if mood == "celebrating":
        # Happy eyes (^) + sparkle overlay.
        happy_a = _sub_eyes(base, "^")
        happy_b = _sub_eyes(base, "*")
        f_a = _add_overlay(happy_a, "* . *")
        f_b = _add_overlay(happy_b, " * . ")
        return [f_a, f_b]

    if mood == "sleeping":
        # Closed eyes (-) + zZz overlay.
        tired = _sub_eyes(base, "-")
        f_a = _add_overlay(tired, "zZz")
        f_b = _add_overlay(tired, " zZ ")
        return [f_a, f_b]

    # Fallback: idle
    return [list(base), _sub_eyes(base, "-")]
