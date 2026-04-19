"""L-shaped reflow: force narrow wrap in rows reserved for the pet overlay.

The outer TUI reserves a rectangle at the top-right of the pty pane for
the buddy's sprite + name + XP + speech bubble + time-with-buddy. Claude
Code doesn't know this rectangle exists; we make its text wrap at a
narrower column for those rows so the pet overlay can paint on top
without clobbering meaningful content.

Design invariants:

  - One coordinate space. Claude writes to a full-width pyte screen;
    we clip writes via the row-dependent right edge. No remapping.
  - Pass-through by default. We override only the pyte events that
    write characters, move the cursor, or erase regions. SGR/OSC/
    mouse/bracketed-paste flow through unchanged.
  - Pet cells are never visible from pyte. The outer TUI paints the
    pet rectangle on top of pyte's buffer during composition; any
    pyte content inside the rectangle is occluded, not reflowed.

## Why this subclasses the Screen, not the Stream

pyte's Stream dispatches events to `self.listener` — i.e. the screen —
not to methods on the Stream subclass. To intercept `draw()`, we have to
override it on the Screen. So this module provides `LReflowHistoryScreen`,
a `pyte.HistoryScreen` subclass whose draw/cursor/erase methods respect
the row-dependent right edge.

Phase 1 (this file): `draw()` with per-char soft-wrap only. Cursor
clamping and erase handling arrive in later phases.
"""
from __future__ import annotations

import pyte


class LReflowHistoryScreen(pyte.HistoryScreen):
    """pyte.HistoryScreen that enforces a row-dependent right edge.

    Args:
      columns, lines:  as for HistoryScreen.
      pet_w:           width of the reserved rectangle in cells.
      pet_h:           height of the reserved rectangle in rows. Can
                       also be a zero-arg callable returning int, for
                       callers with a dynamic pet viewport.
      history, ratio:  forwarded to HistoryScreen.

    For rows `y < pet_h`, writes wrap at `columns - pet_w`. Below, at
    `columns`. All other pyte events inherit HistoryScreen's defaults.
    """

    def __init__(
        self,
        columns: int,
        lines: int,
        *,
        pet_w: int,
        pet_h,
        history: int = 100,
        ratio: float = 0.5,
    ):
        # HistoryScreen wraps method calls via __getattribute__ and may
        # dispatch events during __init__ (e.g. resize → cursor ops). Our
        # overrides read _pet_w / _pet_h_source, so the fields must exist
        # BEFORE super().__init__() runs.
        self._pet_w = int(pet_w)
        self._pet_h_source = pet_h
        # Tracks whether Claude has ever drawn below the pet's vertical
        # zone. Flips True on first such draw / cursor move. Only reset
        # by explicit screen-clearing operations (ED 2/3, reset). The
        # outer widget reads this to decide COLUMNS: narrow while False,
        # full width once True.
        self._content_went_wide: bool = False
        super().__init__(columns, lines, history=history, ratio=ratio)

    # ── content-went-wide tracking ─────────────────────────────────────────

    @property
    def content_went_wide(self) -> bool:
        """True once Claude has drawn or moved the cursor below the pet
        zone. Monotonic within a session — only cleared by an explicit
        screen-clear (ED 2/3, reset)."""
        return self._content_went_wide

    def _note_y(self, y: int) -> None:
        """Call after any operation that may place cursor / content at
        row `y`. Once y >= pet_h, Claude has moved into wide territory
        and we remember it."""
        if not self._content_went_wide and y >= self._pet_h():
            self._content_went_wide = True

    # ── geometry ────────────────────────────────────────────────────────────

    def _pet_h(self) -> int:
        if callable(self._pet_h_source):
            try:
                return int(self._pet_h_source())
            except Exception:
                return 0
        return int(self._pet_h_source)

    def _right_edge(self, y: int) -> int:
        """First column NOT writable on row `y`.

        Above the pet: `columns - pet_w`. Below: `columns`. Callers
        writing at col `x` wrap when `x >= right_edge(y)`.
        """
        if y < self._pet_h():
            return max(0, self.columns - self._pet_w)
        return self.columns

    # ── overrides ───────────────────────────────────────────────────────────

    def _in_pet_box(self, x: int, y: int) -> bool:
        return y < self._pet_h() and x >= self.columns - self._pet_w

    def _clamp_x_to_row_edge(self, x: int, y: int) -> int:
        """If (x, y) is inside the pet rectangle, push x back to the last
        writable column for that row. Otherwise return x unchanged."""
        if self._in_pet_box(x, y):
            return max(0, self.columns - self._pet_w - 1)
        return x

    # ── draw ────────────────────────────────────────────────────────────────

    def draw(self, data: str) -> None:
        """Write printable characters, wrapping at the row's right edge.

        pyte hands us a batched string of printable chars. We iterate
        one char at a time so we can enforce the boundary per cell.
        When the cursor is at or past the edge, we soft-wrap (linefeed
        + carriage_return) before drawing the char.
        """
        for ch in data:
            edge = self._right_edge(self.cursor.y)
            if self.cursor.x >= edge:
                # pyte's linefeed handles scroll-region boundaries for
                # us; carriage_return resets x to 0.
                super().linefeed()
                super().carriage_return()
            super().draw(ch)
            self._note_y(self.cursor.y)

    # ── cursor positioning ─────────────────────────────────────────────────

    def cursor_position(self, line=None, column=None):
        """Absolute cursor move (CUP). Clamp targets that land inside
        the pet rectangle to the last writable column for their row.
        Claude doesn't know the rect exists, so an overlay UI that
        tries to paint in cols 90+ on row 3 lands at col (cols-pet_w-1)
        instead — a lie, but the pet overlay covers the result anyway.
        """
        super().cursor_position(line, column)
        self.cursor.x = self._clamp_x_to_row_edge(self.cursor.x, self.cursor.y)
        self._note_y(self.cursor.y)

    def cursor_forward(self, count=None):
        """Relative cursor move right (CUF). Clamp so we don't step
        into the pet rectangle on the current row."""
        super().cursor_forward(count)
        self.cursor.x = self._clamp_x_to_row_edge(self.cursor.x, self.cursor.y)
        self._note_y(self.cursor.y)

    def cursor_up(self, count=None):
        """CUU — moving up may land on a narrower row where current x
        is past that row's edge. Clamp after the move."""
        super().cursor_up(count)
        self.cursor.x = self._clamp_x_to_row_edge(self.cursor.x, self.cursor.y)
        self._note_y(self.cursor.y)

    def cursor_down(self, count=None):
        super().cursor_down(count)
        self.cursor.x = self._clamp_x_to_row_edge(self.cursor.x, self.cursor.y)
        self._note_y(self.cursor.y)

    def cursor_to_column(self, column=None):
        """CHA / HPA — absolute column set."""
        super().cursor_to_column(column)
        self.cursor.x = self._clamp_x_to_row_edge(self.cursor.x, self.cursor.y)
        self._note_y(self.cursor.y)

    def cursor_to_line(self, line=None):
        """VPA — absolute row set."""
        super().cursor_to_line(line)
        self.cursor.x = self._clamp_x_to_row_edge(self.cursor.x, self.cursor.y)
        self._note_y(self.cursor.y)

    # ── reset on full clear ────────────────────────────────────────────────

    def erase_in_display(self, how: int = 0, *args, **kwargs) -> None:
        """Clearing the whole screen (ED 2 or ED 3) from CLAUDE resets
        the content-went-wide signal so we can flip back to narrow if
        Claude starts fresh (e.g. after `clear`). The outer widget has
        its own clear_visible() for narrow↔wide transitions that bypasses
        this logic."""
        super().erase_in_display(how, *args, **kwargs)
        if how in (2, 3):
            self._content_went_wide = False

    def clear_visible(self) -> None:
        """Erase the visible screen without resetting the content-went-
        wide flag. Called by the outer widget during a narrow↔wide
        transition so the old-width pixels don't linger while Claude
        repaints at the new width."""
        # Reuse pyte's default erase_in_display(2) logic without the
        # flag-reset our override adds.
        super().erase_in_display(2)

    def reset(self) -> None:
        super().reset()
        self._content_went_wide = False

    # ── erase ──────────────────────────────────────────────────────────────

    def erase_in_line(self, how: int = 0, private: bool = False) -> None:
        """EL — cap erases to the row's right edge so pet cells stay
        untouched. Without this, `\\x1b[2K` on a narrow row would clear
        the pet cells' styling too. Pet overlay paints on top so you
        wouldn't see it, but pyte's buffer gets polluted and cursor
        queries would report out-of-band state."""
        edge = self._right_edge(self.cursor.y)
        if edge >= self.columns:
            # Full width row — default is fine.
            super().erase_in_line(how, private)
            return
        self.dirty.add(self.cursor.y)
        if how == 0:
            interval = range(self.cursor.x, edge)
        elif how == 1:
            interval = range(min(self.cursor.x + 1, edge))
        elif how == 2:
            interval = range(edge)
        else:
            return
        line = self.buffer[self.cursor.y]
        for x in interval:
            line[x] = self.cursor.attrs
