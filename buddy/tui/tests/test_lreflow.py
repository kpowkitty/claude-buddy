"""Tests for LReflowHistoryScreen (phase 1: draw() + soft-wrap only).

Unit tests — no PTY, no TUI. Feed bytes to a pyte.ByteStream driving an
LReflowHistoryScreen, then assert on the resulting buffer.

The reflow lives on the SCREEN, not the stream, because pyte dispatches
events (including draw) to the screen, not the stream subclass. See
buddy/tui/lreflow.py for the long explanation.

Covers:
  - Narrow wrap in rows above the pet (y < pet_h).
  - Full-width wrap below the pet.
  - The right-edge boundary (col == COLS - PET_W) is the first col NOT
    written; col == COLS - PET_W - 1 is the last writable col.
  - pet_h can be callable for dynamic geometry.
  - Styled runs (SGR) retain colour across soft-wraps.
"""
from __future__ import annotations

import pyte

from lreflow import LReflowHistoryScreen


def _make(cols: int, lines: int, pet_w: int, pet_h) -> tuple[LReflowHistoryScreen, pyte.ByteStream]:
    screen = LReflowHistoryScreen(cols, lines, pet_w=pet_w, pet_h=pet_h)
    stream = pyte.ByteStream(screen)
    return screen, stream


def _row_text(screen: pyte.Screen, y: int) -> str:
    """Concatenate the visible text on row y, stripping trailing blanks."""
    return "".join(
        (screen.buffer[y][x].data or " ") for x in range(screen.columns)
    ).rstrip()


# ─── narrow zone wrap ────────────────────────────────────────────────────────


def test_long_line_wraps_narrow_in_top_rows() -> None:
    """COLS=40, PET_W=10, PET_H=5. A 60-char line in row 0 should fill
    the first 30 cols, wrap, and continue on row 1 (also narrow)."""
    screen, stream = _make(40, 20, pet_w=10, pet_h=5)
    stream.feed(b"A" * 60)
    assert _row_text(screen, 0) == "A" * 30
    assert _row_text(screen, 1) == "A" * 30


def test_wrap_boundary_is_exact() -> None:
    """Last writable column in a narrow row is COLS - PET_W - 1."""
    screen, stream = _make(40, 20, pet_w=10, pet_h=5)
    stream.feed(b"A" * 30)  # exactly fills narrow width
    assert _row_text(screen, 0) == "A" * 30
    assert _row_text(screen, 1) == ""
    stream.feed(b"B")
    assert _row_text(screen, 1) == "B"


def test_pet_cells_untouched_by_writes() -> None:
    """Writes during phase 1 never land inside the pet rectangle."""
    screen, stream = _make(40, 20, pet_w=10, pet_h=5)
    stream.feed(b"Z" * 200)
    for y in range(5):
        for x in range(30, 40):
            cell = screen.buffer[y][x].data or " "
            assert cell == " ", f"pet cell ({x}, {y}) got written: {cell!r}"


# ─── full-width zone below the pet ───────────────────────────────────────────


def test_rows_below_pet_use_full_width() -> None:
    """Rows y >= pet_h wrap at the full terminal width."""
    screen, stream = _make(40, 20, pet_w=10, pet_h=5)
    stream.feed(b"\r\n" * 5)  # cursor now at row 5, col 0
    stream.feed(b"B" * 60)
    assert _row_text(screen, 5) == "B" * 40
    assert _row_text(screen, 6) == "B" * 20


def test_row_at_pet_h_is_full_width() -> None:
    """pet_h is the first FULL-width row (rows 0..pet_h-1 are narrow)."""
    screen, stream = _make(40, 20, pet_w=10, pet_h=5)
    stream.feed(b"\r\n" * 5)
    stream.feed(b"X" * 40)
    assert _row_text(screen, 5) == "X" * 40


# ─── dynamic pet_h (callable) ────────────────────────────────────────────────


def test_pet_h_can_be_callable() -> None:
    """Dynamic callers (e.g. a live habitat widget) pass a lambda."""
    h = [3]
    screen, stream = _make(40, 20, pet_w=10, pet_h=lambda: h[0])
    stream.feed(b"A" * 60)
    assert _row_text(screen, 0) == "A" * 30
    assert _row_text(screen, 1) == "A" * 30


def test_callable_pet_h_read_dynamically() -> None:
    """Changing the callable's return value between writes picks up
    the new edge on the next draw."""
    h = [5]
    screen, stream = _make(40, 20, pet_w=10, pet_h=lambda: h[0])
    stream.feed(b"\r\n" * 3)
    stream.feed(b"Q" * 5)
    assert _row_text(screen, 3) == "Q" * 5
    h[0] = 2  # shrink — row 3 now outside narrow zone
    stream.feed(b"W" * 40)
    assert _row_text(screen, 3).startswith("Q" * 5)
    assert "W" * 35 in _row_text(screen, 3)


# ─── pass-through: SGR, line feed ────────────────────────────────────────────


def test_sgr_colours_survive_soft_wrap() -> None:
    """SGR state is on the screen, not the stream — our soft-wrap uses
    the screen's own linefeed/carriage_return, which preserves current
    attributes. So red-on before a wrap stays red-on after."""
    screen, stream = _make(40, 20, pet_w=10, pet_h=5)
    stream.feed(b"\x1b[31m" + b"A" * 40 + b"\x1b[0m")
    assert screen.buffer[0][0].fg == "red"
    assert screen.buffer[1][0].fg == "red"


def test_explicit_linefeed_advances_to_full_width_if_beyond_pet_h() -> None:
    screen, stream = _make(40, 20, pet_w=10, pet_h=3)
    stream.feed(b"A" * 5 + b"\r\n" + b"\r\n" + b"\r\n" + b"B" * 40)
    assert _row_text(screen, 0) == "A" * 5
    assert _row_text(screen, 3) == "B" * 40


# ─── phase 2: cursor clamping ───────────────────────────────────────────────


def test_absolute_cursor_move_into_pet_clamps() -> None:
    """CUP targeting (row=2, col=35) with pet_w=10 pet_h=5 lands inside
    the rect. Clamp pushes cursor to col=29 (cols-pet_w-1)."""
    screen, stream = _make(40, 20, pet_w=10, pet_h=5)
    stream.feed(b"\x1b[3;36H")  # CUP 3,36 → 1-based row=3, col=36 → 0-based (2, 35)
    assert screen.cursor.y == 2
    assert screen.cursor.x == 29  # clamped to cols - pet_w - 1


def test_absolute_cursor_move_outside_pet_unchanged() -> None:
    screen, stream = _make(40, 20, pet_w=10, pet_h=5)
    stream.feed(b"\x1b[10;20H")  # row 10, col 20 → below pet, well inside
    assert screen.cursor.y == 9
    assert screen.cursor.x == 19


def test_cursor_forward_clamps_at_narrow_edge() -> None:
    screen, stream = _make(40, 20, pet_w=10, pet_h=5)
    # Put cursor at (0, 20) in the narrow zone, then try to go right 15.
    stream.feed(b"\x1b[1;21H")  # (0, 20) 1-based
    stream.feed(b"\x1b[15C")    # CUF 15
    # Without clamp: 20 + 15 = 35 (inside pet). Clamped to 29.
    assert screen.cursor.x == 29


def test_cursor_up_lands_on_narrow_row_and_clamps() -> None:
    """Cursor is at col 35 on row 10 (full width, fine). Move up 7 rows
    to row 3 (narrow). Our clamp yanks it back to col 29."""
    screen, stream = _make(40, 20, pet_w=10, pet_h=5)
    stream.feed(b"\x1b[11;36H")  # (10, 35) 1-based
    assert screen.cursor.x == 35
    stream.feed(b"\x1b[7A")      # CUU 7 → row 3 (narrow zone)
    assert screen.cursor.y == 3
    assert screen.cursor.x == 29


def test_cursor_to_column_clamps() -> None:
    screen, stream = _make(40, 20, pet_w=10, pet_h=5)
    # Move to narrow row 0, then CHA col 36 (would be in pet).
    stream.feed(b"\x1b[1;1H")
    stream.feed(b"\x1b[36G")  # CHA col 36
    assert screen.cursor.x == 29


def test_cursor_down_from_full_to_narrow_clamps() -> None:
    """Moving down from a wide row into a narrow row pulls cursor to
    the last writable column for that row."""
    screen, stream = _make(40, 20, pet_w=10, pet_h=5)
    stream.feed(b"\x1b[10;36H")  # row 9, col 35 (full width)
    stream.feed(b"\x1b[7A")       # CUU 7 → row 2, still col 35 → clamp to 29
    assert screen.cursor.x == 29


# ─── phase 3: erase handling ───────────────────────────────────────────────


def _cell_style_attrs(screen: pyte.Screen, y: int, x: int):
    """Return (fg, bg) of the cell. After an erase, cells take the
    cursor's current attrs — so a red cursor that erases paints red
    background cells."""
    c = screen.buffer[y][x]
    return (c.fg, c.bg)


def test_erase_in_line_0_spares_pet_cells() -> None:
    """CSI 0 K erases from cursor to end of line. On a narrow row it
    must stop at the narrow edge so pet cells stay default."""
    screen, stream = _make(40, 20, pet_w=10, pet_h=5)
    # Paint a red background on the WHOLE narrow row by walking a red
    # cursor across it first.
    stream.feed(b"\x1b[41m")       # set bg=red on cursor
    stream.feed(b"\x1b[1;1H")      # (0,0)
    stream.feed(b"\x1b[2K")        # clear line 0 — bounded to narrow edge
    # Now cols 0..29 should have bg=red, cols 30..39 still default.
    for x in range(30):
        assert screen.buffer[0][x].bg == "red", f"col {x} missing red"
    for x in range(30, 40):
        assert screen.buffer[0][x].bg != "red", f"pet col {x} leaked red"


def test_erase_in_line_0_on_full_row_clears_entire_row() -> None:
    """Below pet_h, erase uses pyte's default (full cols)."""
    screen, stream = _make(40, 20, pet_w=10, pet_h=5)
    stream.feed(b"\x1b[41m")       # red bg
    stream.feed(b"\x1b[10;1H")     # row 9 (below pet)
    stream.feed(b"\x1b[2K")        # clear whole row
    for x in range(40):
        assert screen.buffer[9][x].bg == "red", f"col {x} on full row not cleared"


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
    # Stay in narrow zone first — flag should remain False.
    stream.feed(b"hello")
    assert screen.content_went_wide is False
    # Move cursor down past PET_H and draw.
    stream.feed(b"\r\n" * 6 + b"world")
    assert screen.content_went_wide is True


def test_content_went_wide_flips_via_cursor_position() -> None:
    """Absolute cursor moves below the pet zone also flip the flag."""
    screen = LReflowHistoryScreen(80, 40, pet_w=24, pet_h=5)
    stream = pyte.ByteStream(screen)
    assert screen.content_went_wide is False
    stream.feed(b"\x1b[10;1H")  # CUP row 10 (below PET_H=5)
    assert screen.content_went_wide is True


def test_content_went_wide_resets_on_full_clear() -> None:
    """ED 2 / ED 3 / reset should reset the flag so a `clear` brings us
    back to narrow mode."""
    screen = LReflowHistoryScreen(80, 40, pet_w=24, pet_h=5)
    stream = pyte.ByteStream(screen)
    stream.feed(b"\x1b[10;1H")
    assert screen.content_went_wide is True
    # ED 2 — erase whole display.
    stream.feed(b"\x1b[2J")
    assert screen.content_went_wide is False


def test_content_went_wide_stays_sticky_until_clear() -> None:
    """Once wide, we stay wide even if Claude moves the cursor back up."""
    screen = LReflowHistoryScreen(80, 40, pet_w=24, pet_h=5)
    stream = pyte.ByteStream(screen)
    stream.feed(b"\x1b[10;1H")  # go wide
    stream.feed(b"\x1b[1;1H")   # back to top
    assert screen.content_went_wide is True


def test_erase_in_line_1_respects_narrow_edge() -> None:
    """Mode 1 = start-of-line to cursor. If cursor itself is past the
    narrow edge (shouldn't normally happen since we clamp), cap at edge."""
    screen, stream = _make(40, 20, pet_w=10, pet_h=5)
    stream.feed(b"\x1b[41m")
    stream.feed(b"\x1b[1;20H")     # (0, 19)
    stream.feed(b"\x1b[1K")        # erase start..cursor
    for x in range(20):
        assert screen.buffer[0][x].bg == "red"
    for x in range(30, 40):
        assert screen.buffer[0][x].bg != "red"
