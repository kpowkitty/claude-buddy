#!/usr/bin/env python3
"""Buddy renderer — run this in a second terminal.

Watches ~/.claude/buddy/state.json and ~/.claude/buddy/progression.json, draws
your buddy with mood-dependent animation. Press q or Ctrl-C to quit.
"""
from __future__ import annotations

import curses
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from state import STATE, PROGRESSION, read_json, derive_mood  # noqa: E402
from species import find_species  # noqa: E402
from sprites import frames_for  # noqa: E402

RARITY_COLOR_PAIR = {
    "common": 7,
    "uncommon": 2,
    "rare": 4,
    "epic": 5,
    "legendary": 3,
}


def _init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)
    curses.init_pair(4, curses.COLOR_BLUE, -1)
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)
    curses.init_pair(7, curses.COLOR_WHITE, -1)


def _mood_status(mood: str, tool: str | None) -> str:
    if mood == "watching":
        return f"watching your {tool or 'work'}..."
    return {
        "idle": "just vibing",
        "attentive": "listening...",
        "celebrating": "yay! done!",
        "sleeping": "zZz...",
    }.get(mood, "")


def _draw(stdscr, tick: int):
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    prog = read_json(PROGRESSION, None)
    if not prog:
        msg = "No buddy yet. Run `/buddy hatch` in Claude Code."
        stdscr.addstr(h // 2, max(0, (w - len(msg)) // 2), msg)
        stdscr.refresh()
        return

    state = read_json(STATE, {})
    mood = derive_mood(state) if state else "idle"

    rarity, species = find_species(prog["species_id"])
    if species is None:
        stdscr.addstr(0, 0, f"Unknown species: {prog['species_id']}")
        stdscr.refresh()
        return

    frames = frames_for(prog["species_id"], mood)
    # At 10fps, 1 tick = 100ms.
    # Idle: frame A (open eyes) almost always; brief blink (frame B) for ~2 ticks every ~25s.
    # Sleeping: alternate slowly (every ~1s) to animate zZz.
    # Other moods: small back-and-forth every ~0.5s.
    if mood == "idle":
        cycle = tick % 250  # 25s at 10fps
        frame_idx = 1 if cycle < 2 else 0
    elif mood == "sleeping":
        frame_idx = (tick // 10) % 2
    else:
        frame_idx = (tick // 5) % 2
    sprite = frames[frame_idx]

    color_pair = curses.color_pair(RARITY_COLOR_PAIR.get(rarity, 1))
    attr = color_pair | (curses.A_BOLD if rarity in ("epic", "legendary") else 0)

    sprite_h = len(sprite)
    sprite_w = max(len(l) for l in sprite) if sprite else 0
    start_y = max(0, (h - sprite_h - 4) // 2)
    start_x = max(0, (w - sprite_w) // 2)

    for i, line in enumerate(sprite):
        if start_y + i >= h:
            break
        try:
            stdscr.addstr(start_y + i, start_x, line[: w - start_x], attr)
        except curses.error:
            pass

    name = prog.get("name") or species["name"]
    header = f"★ {name} · {species['name']} · {rarity} ★"
    status = _mood_status(mood, state.get("current_tool") if state else None)
    footer_y = min(h - 2, start_y + sprite_h + 1)
    try:
        stdscr.addstr(footer_y, max(0, (w - len(header)) // 2), header, attr)
        stdscr.addstr(footer_y + 1, max(0, (w - len(status)) // 2), status)
    except curses.error:
        pass

    # Speech bubble: show for up to SPEECH_TTL seconds after speech_ts.
    speech = state.get("speech") if state else None
    speech_ts = state.get("speech_ts", 0) if state else 0
    SPEECH_TTL = 12
    if speech and time.time() - speech_ts < SPEECH_TTL:
        _draw_bubble(stdscr, speech, start_y, start_x, sprite_w, w, attr)

    hint = "q to quit"
    try:
        stdscr.addstr(h - 1, max(0, w - len(hint) - 1), hint, curses.A_DIM)
    except curses.error:
        pass

    stdscr.refresh()


def _draw_bubble(stdscr, text: str, sprite_y: int, sprite_x: int, sprite_w: int, screen_w: int, attr):
    """Draw a speech bubble above the sprite."""
    text = text.strip()
    if not text:
        return
    # Wrap to at most 40 chars
    max_w = min(40, screen_w - 4)
    words = text.split()
    lines = []
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
    bubble_x = max(0, sprite_x + (sprite_w - bubble_w) // 2)
    bubble_y = max(0, sprite_y - len(lines) - 3)
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


def _loop(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(100)  # 10fps
    _init_colors()
    tick = 0
    while True:
        _draw(stdscr, tick)
        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q"), 27):
            break
        tick += 1


def main() -> int:
    try:
        curses.wrapper(_loop)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
