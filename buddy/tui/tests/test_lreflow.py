"""Tests for LReflowHistoryScreen.

Reflow of the L-shaped reserved rectangle now happens at render time in
PtyTerminal._virtual_rows — the screen itself is a plain HistoryScreen
with one extra signal: `content_went_wide`, which the outer widget reads
to decide whether to tell Claude the narrow or the full COLUMNS.

This file covers the width-flip signal and the narrow↔wide COLUMNS
math in `_effective_child_cols`.
"""
from __future__ import annotations

import pyte

from lreflow import LReflowHistoryScreen


# ─── adaptive COLUMNS ──────────────────────────────────────────────────────


def test_effective_child_cols_narrow_before_content_goes_wide() -> None:
    """Before Claude draws below the pet zone, we tell it COLS - PET_W."""
    from pty_terminal import _effective_child_cols, PET_W
    assert _effective_child_cols(180, went_wide=False) == 180 - PET_W


def test_effective_child_cols_full_width_once_content_went_wide() -> None:
    """Once Claude has drawn below the pet zone, we tell it full cols."""
    from pty_terminal import _effective_child_cols
    assert _effective_child_cols(180, went_wide=True) == 180


def test_effective_child_cols_floors_at_20() -> None:
    """Pathological tiny width — don't hand Claude a negative or too-small cols."""
    from pty_terminal import _effective_child_cols
    assert _effective_child_cols(10, went_wide=False) >= 20


def test_content_went_wide_starts_false() -> None:
    from pty_terminal import PET_H
    screen = LReflowHistoryScreen(80, PET_H + 20, pet_w=24, pet_h=PET_H)
    assert screen.content_went_wide is False


def test_content_went_wide_flips_when_draw_crosses_pet_h() -> None:
    """A write that lands on row >= PET_H flips the flag."""
    screen = LReflowHistoryScreen(80, 40, pet_w=24, pet_h=5)
    stream = pyte.ByteStream(screen)
    stream.feed(b"hello")
    assert screen.content_went_wide is False
    stream.feed(b"\r\n" * 6 + b"world")
    assert screen.content_went_wide is True


def test_content_went_wide_flips_via_cursor_position() -> None:
    """Absolute cursor moves below the pet zone also flip the flag."""
    screen = LReflowHistoryScreen(80, 40, pet_w=24, pet_h=5)
    stream = pyte.ByteStream(screen)
    assert screen.content_went_wide is False
    stream.feed(b"\x1b[10;1H")
    assert screen.content_went_wide is True


def test_content_went_wide_resets_on_full_clear() -> None:
    """ED 2 / ED 3 / reset clears the flag so a `clear` brings us back to
    narrow mode."""
    screen = LReflowHistoryScreen(80, 40, pet_w=24, pet_h=5)
    stream = pyte.ByteStream(screen)
    stream.feed(b"\x1b[10;1H")
    assert screen.content_went_wide is True
    stream.feed(b"\x1b[2J")
    assert screen.content_went_wide is False


def test_content_went_wide_stays_sticky_until_clear() -> None:
    """Once wide, we stay wide even if Claude moves the cursor back up."""
    screen = LReflowHistoryScreen(80, 40, pet_w=24, pet_h=5)
    stream = pyte.ByteStream(screen)
    stream.feed(b"\x1b[10;1H")
    stream.feed(b"\x1b[1;1H")
    assert screen.content_went_wide is True


def test_clear_visible_preserves_went_wide_flag() -> None:
    """clear_visible is the outer widget's narrow↔wide transition hook
    and must NOT reset the went_wide flag (otherwise we'd ping-pong)."""
    screen = LReflowHistoryScreen(80, 40, pet_w=24, pet_h=5)
    stream = pyte.ByteStream(screen)
    stream.feed(b"\x1b[10;1H")
    assert screen.content_went_wide is True
    screen.clear_visible()
    assert screen.content_went_wide is True


def test_pet_h_can_be_callable() -> None:
    """Dynamic callers (e.g. a live habitat widget) pass a lambda."""
    h = [3]
    screen = LReflowHistoryScreen(80, 40, pet_w=24, pet_h=lambda: h[0])
    stream = pyte.ByteStream(screen)
    stream.feed(b"\x1b[4;1H")  # row 3 — at/below pet_h=3
    assert screen.content_went_wide is True


# ─── pyte is now a plain full-width screen ─────────────────────────────────


def test_writes_fill_full_width() -> None:
    """With the write-time reflow gone, pyte stores Claude's output at
    full width; the L-shape is a render-time concern."""
    screen = LReflowHistoryScreen(40, 20, pet_w=10, pet_h=5)
    stream = pyte.ByteStream(screen)
    stream.feed(b"A" * 40)
    row0 = "".join((screen.buffer[0][x].data or " ") for x in range(40))
    assert row0 == "A" * 40
