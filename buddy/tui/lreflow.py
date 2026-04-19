"""L-shaped reflow signal: tracks when Claude's content has grown below
the reserved pet zone, so the outer widget can flip Claude's COLUMNS
from narrow (cols - PET_W) to full width.

Reflow itself is done at render time in PtyTerminal._virtual_rows — any
content pyte writes into the top-right reserved rectangle is split onto
a new visual line instead of being painted under the habitat overlay.
This file only carries the narrow↔wide width-flip signal.
"""
from __future__ import annotations

import pyte


class LReflowHistoryScreen(pyte.HistoryScreen):
    """pyte.HistoryScreen that tracks whether Claude has drawn below the
    pet zone.

    Args:
      columns, lines:  as for HistoryScreen.
      pet_w:           width of the reserved rectangle in cells. Unused
                       here, kept for API compatibility with callers.
      pet_h:           height of the reserved rectangle in rows. Can
                       also be a zero-arg callable returning int.
      history, ratio:  forwarded to HistoryScreen.
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
        self._pet_w = int(pet_w)
        self._pet_h_source = pet_h
        self._content_went_wide: bool = False
        super().__init__(columns, lines, history=history, ratio=ratio)

    @property
    def content_went_wide(self) -> bool:
        """True once Claude has drawn or moved the cursor below the pet
        zone. Monotonic within a session — only cleared by an explicit
        screen-clear (ED 2/3, reset)."""
        return self._content_went_wide

    def _pet_h(self) -> int:
        if callable(self._pet_h_source):
            try:
                return int(self._pet_h_source())
            except Exception:
                return 0
        return int(self._pet_h_source)

    def _note_y(self, y: int) -> None:
        if not self._content_went_wide and y >= self._pet_h():
            self._content_went_wide = True

    def draw(self, data: str) -> None:
        super().draw(data)
        self._note_y(self.cursor.y)

    def cursor_position(self, line=None, column=None):
        super().cursor_position(line, column)
        self._note_y(self.cursor.y)

    def cursor_down(self, count=None):
        super().cursor_down(count)
        self._note_y(self.cursor.y)

    def cursor_to_line(self, line=None):
        super().cursor_to_line(line)
        self._note_y(self.cursor.y)

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
        super().erase_in_display(2)

    def reset(self) -> None:
        super().reset()
        self._content_went_wide = False
