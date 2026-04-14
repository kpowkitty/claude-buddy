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
from dataclasses import dataclass

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from state import STATE, PROGRESSION, read_json, derive_mood  # noqa: E402
from species import find_species  # noqa: E402
from sprites import frames_for  # noqa: E402
from layout import compute_layout  # noqa: E402
from regions import draw_sprite, draw_header, draw_status, draw_hint, draw_bubble  # noqa: E402
from input import LineEditor, KeyResult  # noqa: E402
from slots import Spacer, draw_prompt_area  # noqa: E402

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


SPEECH_TTL = 12


@dataclass
class Ctx:
    sprite: list[str]
    attr: int
    header_text: str
    status_text: str
    bubble_text: str | None
    mood: str


def _pick_frame(tick: int, mood: str, frames: list[list[str]]) -> list[str]:
    # At 10fps, 1 tick = 100ms.
    # Idle: frame A (open eyes) almost always; brief blink (frame B) for ~2 ticks every ~25s.
    # Sleeping: alternate slowly (every ~1s) to animate zZz.
    # Other moods: small back-and-forth every ~0.5s.
    if mood == "idle":
        cycle = tick % 250
        frame_idx = 1 if cycle < 2 else 0
    elif mood == "sleeping":
        frame_idx = (tick // 10) % 2
    else:
        frame_idx = (tick // 5) % 2
    return frames[frame_idx]


def _build_ctx(tick: int) -> Ctx | str:
    """Returns a Ctx on the happy path, or a string to render as a standalone message."""
    prog = read_json(PROGRESSION, None)
    if not prog:
        return "No buddy yet. Run `/buddy hatch` in Claude Code."

    state = read_json(STATE, {})
    mood = derive_mood(state) if state else "idle"

    rarity, species = find_species(prog["species_id"])
    if species is None:
        return f"Unknown species: {prog['species_id']}"

    sprite = _pick_frame(tick, mood, frames_for(prog["species_id"], mood))
    color_pair = curses.color_pair(RARITY_COLOR_PAIR.get(rarity, 1))
    attr = color_pair | (curses.A_BOLD if rarity in ("epic", "legendary") else 0)

    name = prog.get("name") or species["name"]
    header_text = f"★ {name} · {species['name']} · {rarity} ★"
    status_text = _mood_status(mood, state.get("current_tool") if state else None)

    bubble_text = None
    speech = state.get("speech") if state else None
    speech_ts = state.get("speech_ts", 0) if state else 0
    if speech and time.time() - speech_ts < SPEECH_TTL:
        bubble_text = speech

    return Ctx(
        sprite=sprite,
        attr=attr,
        header_text=header_text,
        status_text=status_text,
        bubble_text=bubble_text,
        mood=mood,
    )


def _draw_message(stdscr, text: str) -> None:
    h, w = stdscr.getmaxyx()
    try:
        stdscr.addstr(h // 2, max(0, (w - len(text)) // 2), text)
    except curses.error:
        pass


def _render(stdscr, ctx: Ctx, slots) -> None:
    h, w = stdscr.getmaxyx()
    sprite_h = len(ctx.sprite)
    sprite_w = max(len(l) for l in ctx.sprite) if ctx.sprite else 0
    prompt_h = max((s.min_h for s in slots), default=0)
    layout = compute_layout(h, w, sprite_h, sprite_w, prompt_h=prompt_h)

    draw_sprite(stdscr, layout.sprite, ctx.sprite, ctx.attr)
    draw_header(stdscr, layout.header, ctx.header_text, ctx.attr)
    draw_status(stdscr, layout.status, ctx.status_text)
    if ctx.bubble_text:
        draw_bubble(stdscr, layout.sprite, ctx.bubble_text, ctx.attr)
    draw_prompt_area(stdscr, layout.prompt, slots, ctx)
    draw_hint(stdscr, layout.hint, "q to quit")


def _draw(stdscr, tick: int, slots):
    stdscr.erase()
    ctx = _build_ctx(tick)
    if isinstance(ctx, str):
        _draw_message(stdscr, ctx)
    else:
        _render(stdscr, ctx, slots)
    stdscr.refresh()


def _loop(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(100)  # 10fps
    _init_colors()
    editor = LineEditor()
    slots = [Spacer()]  # v1: invisible filler. chat PR adds InputSlot + BuddyBoxSlot.
    tick = 0
    while True:
        _draw(stdscr, tick, slots)
        ch = stdscr.getch()
        if ch == curses.KEY_RESIZE:
            # Redraw immediately at the new dimensions instead of waiting for next tick.
            _draw(stdscr, tick, slots)
            continue
        if editor.handle_key(ch) is KeyResult.QUIT:
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
