"""Keyboard input handling for the buddy window.

`LineEditor` owns a single-line text buffer and interprets keystrokes. It's
dormant in the current build — no rendering, and only the QUIT path is wired
into the main loop. When the mini-terminal lands, the same editor will be
mounted inside an InputSlot and its buffer/render paths will come alive.
"""
from __future__ import annotations

import curses
from enum import Enum, auto


class KeyResult(Enum):
    IGNORED = auto()
    INSERTED = auto()
    DELETED = auto()
    SUBMITTED = auto()
    QUIT = auto()


class LineEditor:
    def __init__(self) -> None:
        self.buffer: str = ""

    def handle_key(self, ch: int) -> KeyResult:
        if ch == -1:
            return KeyResult.IGNORED
        # Quit keys are always honored while the editor is inactive.
        # When the mini-terminal lands, these will only apply when the
        # buffer is empty (so typing 'q' inserts a 'q' instead of quitting).
        if not self.buffer and ch in (ord("q"), ord("Q"), 27):
            return KeyResult.QUIT
        if ch in (ord("\n"), ord("\r"), curses.KEY_ENTER):
            if self.buffer:
                return KeyResult.SUBMITTED
            return KeyResult.IGNORED
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if self.buffer:
                self.buffer = self.buffer[:-1]
                return KeyResult.DELETED
            return KeyResult.IGNORED
        if 32 <= ch < 127:
            self.buffer += chr(ch)
            return KeyResult.INSERTED
        return KeyResult.IGNORED

    def take(self) -> str:
        out = self.buffer
        self.buffer = ""
        return out
