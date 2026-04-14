"""Region renderers.

Each function owns a rectangle (or anchors to one) and draws a single piece
of UI. All curses errors are caught at the boundary so a too-small terminal
degrades gracefully instead of crashing.
"""
from __future__ import annotations

import curses

from layout import Rect


def draw_sprite(stdscr, rect: Rect, sprite: list[str], attr) -> None:
    h, w = stdscr.getmaxyx()
    for i, line in enumerate(sprite):
        if rect.y + i >= h:
            break
        try:
            stdscr.addstr(rect.y + i, rect.x, line[: w - rect.x], attr)
        except curses.error:
            pass


def draw_header(stdscr, rect: Rect, text: str, attr) -> None:
    try:
        stdscr.addstr(rect.y, max(0, (rect.w - len(text)) // 2), text, attr)
    except curses.error:
        pass


def draw_status(stdscr, rect: Rect, text: str) -> None:
    try:
        stdscr.addstr(rect.y, max(0, (rect.w - len(text)) // 2), text)
    except curses.error:
        pass


def draw_hint(stdscr, rect: Rect, text: str) -> None:
    try:
        stdscr.addstr(rect.y, max(0, rect.w - len(text) - 1), text, curses.A_DIM)
    except curses.error:
        pass


def draw_bubble(stdscr, anchor: Rect, text: str, attr) -> None:
    """Speech bubble anchored above the given sprite rect.

    Self-sizes based on text content (wrapped to ≤40 chars). Anchor provides
    the sprite's position so the bubble can center over it.
    """
    text = text.strip()
    if not text:
        return
    _, screen_w = stdscr.getmaxyx()
    max_w = min(40, screen_w - 4)
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        if len(cur) + len(word) + 1 <= max_w:
            cur = (cur + " " + word).strip()
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if not lines:
        return
    bubble_w = max(len(l) for l in lines) + 4
    bubble_x = max(0, anchor.x + (anchor.w - bubble_w) // 2)
    bubble_y = max(0, anchor.y - len(lines) - 3)
    top = "╭" + "─" * (bubble_w - 2) + "╮"
    bot = "╰" + "─" * (bubble_w - 2) + "╯"
    try:
        stdscr.addstr(bubble_y, bubble_x, top, attr)
        for i, line in enumerate(lines):
            content = "│ " + line.ljust(bubble_w - 4) + " │"
            stdscr.addstr(bubble_y + 1 + i, bubble_x, content, attr)
        stdscr.addstr(bubble_y + 1 + len(lines), bubble_x, bot, attr)
        tail_x = bubble_x + bubble_w // 2
        stdscr.addstr(bubble_y + 2 + len(lines), tail_x, "▼", attr)
    except curses.error:
        pass
