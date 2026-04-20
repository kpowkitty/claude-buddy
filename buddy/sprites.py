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

# Best-effort mouth → smile swaps for the `petted` mood. Applied in order,
# all matches replaced. Species with no recognisable mouth just stay as-is
# (still get closed eyes + prrr bubble). Per-species overrides can come later.
#
# NOTE on what is and isn't a mouth: `> v <` on kitsune is paws holding
# something, not a mouth. `/v\` on owlet is a beak. Conservative list
# intentionally — better to miss a smile than swap a body part.
_PETTED_MOUTH_SWAPS = [
    ("^.^", "^‿^"),           # kitsune: eyes stay happy, the `.` between
                               # them (which is the mouth) becomes a smile.
    ("\\VV/", "\\uu/"),       # dragonling
]


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


def _apply_tail_b(frame_b, species):
    """Overlay the species' optional `tail_b` row-overrides onto a frame.

    Species opt into tail animation by declaring `tail_b: {row_index: line}`
    alongside their art. Any species without `tail_b` returns unchanged.
    """
    tail_b = species.get("tail_b")
    if not tail_b:
        return frame_b
    return [tail_b.get(i, line) for i, line in enumerate(frame_b)]


def _apply_overrides(base, overrides):
    """Overlay a {row_index: line} dict onto base art. Same shape as
    `tail_b` but generalized — used by multi-frame species like ember."""
    return [overrides.get(i, line) for i, line in enumerate(base)]


def blink_frame(species_id: str):
    """Eyes-closed variant of the base art. Used by callers that animate
    the tail and blink on independent cycles — they grab the wag from
    frames_for() and drop in this blink frame on the occasional tick."""
    _, species = find_species(species_id)
    if species is None:
        return ["?"]
    return _sub_eyes(list(species["art"]), "-")


def frames_for(species_id: str, mood: str):
    """Return a list of frames (each a list of strings) for given species
    and mood. Usually 2 frames (A/B), but species with a `frames` list
    (e.g. ember's flicker) return N frames for the habitat to cycle.

    Multi-frame species keep flickering through every awake mood — the
    animation is part of their identity (a flame doesn't freeze when
    you look at it). We sub the mood's eyes onto each variant and
    return the whole list. Sleeping is the one exception: still pet.
    """
    _, species = find_species(species_id)
    if species is None:
        return [["?"], ["?"]]
    base = list(species["art"])

    # Multi-frame species: animate across all awake moods.
    if mood != "sleeping" and species.get("frames"):
        variants = [list(base)] + [_apply_overrides(base, ov) for ov in species["frames"]]
        mood_eye = {"attentive": "O", "watching": "@", "celebrating": "^", "petted": "-"}.get(mood)
        if mood_eye is not None:
            variants = [_sub_eyes(v, mood_eye) for v in variants]
        return variants

    if mood == "idle":
        # Frame A = base. Frame B = blink (eyes → -).
        f_a = list(base)
        f_b = _sub_eyes(base, "-")
    elif mood == "attentive":
        # Wide eyes (O/0) and slight mouth twitch.
        f_a = _sub_eyes(base, "O")
        f_b = _sub_eyes(base, "0")
    elif mood == "watching":
        # Fixated eyes (@).
        f_a = _sub_eyes(base, "@")
        f_b = _sub_eyes(base, "@")
    elif mood == "celebrating":
        # Happy eyes (^) + sparkle overlay.
        happy_a = _sub_eyes(base, "^")
        happy_b = _sub_eyes(base, "*")
        f_a = _add_overlay(happy_a, "* . *")
        f_b = _add_overlay(happy_b, " * . ")
    elif mood == "sleeping":
        # Closed eyes (-) + zZz overlay.
        tired = _sub_eyes(base, "-")
        f_a = _add_overlay(tired, "zZz")
        f_b = _add_overlay(tired, " zZ ")
    elif mood == "petted":
        # Closed eyes + best-effort smile. Both frames identical so the
        # buddy reads as "still, content" rather than blinking. Speech
        # bubble ("prrr") is handled by app.action_pet, not here.
        # `^` eyes (kitsune, moth) are already happy — leave them alone;
        # o-style eyes close to `-`.
        closed = _sub_eyes(base, "-")
        smiled = _mouth_sub(closed, _PETTED_MOUTH_SWAPS)
        f_a = smiled
        f_b = smiled
    else:
        f_a = list(base)
        f_b = _sub_eyes(base, "-")

    # Overlay the wag onto frame B so awake moods animate the tail. Moods
    # that use _add_overlay prepend an extra line, shifting row indices —
    # but tail_b is keyed against the base art, so we apply BEFORE the
    # overlay. Re-derive frame B for those moods so the shift doesn't
    # corrupt tail_b's indices. Sleeping skips the wag entirely — the pet
    # is resting, the tail is still.
    if species.get("tail_b"):
        if mood == "idle":
            # Idle frame B is normally a blink (eyes closed). For tail
            # species we want the wag to alternate INDEPENDENTLY of the
            # blink — so frame B keeps eyes open and just shifts the
            # tail. The habitat picks the rare blink separately.
            f_b = _apply_tail_b(list(base), species)
        elif mood == "celebrating":
            f_b = _add_overlay(_apply_tail_b(_sub_eyes(base, "*"), species), " * . ")
        elif mood == "sleeping":
            pass  # No tail wag while asleep; frame B keeps the base tail.
        elif mood == "petted":
            # Keep the "still / content" read — both frames identical, just
            # with the tail wagging underneath.
            closed = _sub_eyes(_apply_tail_b(base, species), "-")
            wag = _mouth_sub(closed, _PETTED_MOUTH_SWAPS)
            f_b = wag
        else:
            f_b = _apply_tail_b(f_b, species)
    return [f_a, f_b]
