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
    """Speech bubble stacked above the anchor rect.

    Bubble width matches the anchor's column width so it stays aligned with
    the buddy box. Height grows by wrapping more lines, capped so the bubble
    + tail never extend past the top of the terminal.
    """
    text = text.strip()
    if not text:
        return
    screen_h, _ = stdscr.getmaxyx()

    bubble_w = max(6, anchor.w)  # need room for "│ x │" minimum
    inner_w = bubble_w - 4       # text area inside borders
    if inner_w <= 0:
        return

    # Wrap to inner_w. Words longer than inner_w get hard-broken.
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        while len(word) > inner_w:
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(word[:inner_w])
            word = word[inner_w:]
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= inner_w:
            cur = cur + " " + word
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if not lines:
        return

    # Total bubble footprint = top border + N lines + bottom border + tail = N + 3.
    # Cap so bubble doesn't extend above the terminal.
    max_lines = max(1, anchor.y - 1)  # leave at least row 0 free
    if len(lines) + 3 > max_lines:
        keep = max(1, max_lines - 3)
        lines = lines[:keep]
        if lines and inner_w >= 1:
            # Mark truncation with ellipsis on the last visible line.
            last = lines[-1]
            if len(last) >= inner_w:
                last = last[: inner_w - 1] + "…"
            else:
                last = (last + "…")[:inner_w]
            lines[-1] = last

    bubble_x = max(0, anchor.x)
    bubble_y = max(0, anchor.y - len(lines) - 3)
    top = "╭" + "─" * (bubble_w - 2) + "╮"
    bot = "╰" + "─" * (bubble_w - 2) + "╯"
    try:
        stdscr.addstr(bubble_y, bubble_x, top, attr)
        for i, line in enumerate(lines):
            content = "│ " + line.ljust(inner_w) + " │"
            stdscr.addstr(bubble_y + 1 + i, bubble_x, content, attr)
        stdscr.addstr(bubble_y + 1 + len(lines), bubble_x, bot, attr)
        tail_x = bubble_x + bubble_w // 2
        if bubble_y + 2 + len(lines) < screen_h:
            stdscr.addstr(bubble_y + 2 + len(lines), tail_x, "▼", attr)
    except curses.error:
        pass
