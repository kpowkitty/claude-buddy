"""Prompt-area plug-in surface.

The prompt area (bottom strip of the buddy window) is a row of `PromptSlot`
widgets laid out left-to-right. Adding a feature (input, buddy-in-a-box, mood
badge, rarity meter, tool indicator) is a matter of writing a new slot class
and registering it — no layout or renderer changes required.
"""
from __future__ import annotations

import curses
from typing import Protocol, runtime_checkable

from input import KeyResult
from layout import Rect
from regions import draw_bubble


@runtime_checkable
class PromptSlot(Protocol):
    min_w: int   # minimum columns required; 0 means "none"
    min_h: int   # minimum rows required
    flex: int    # 0 = fixed width, >0 = share of leftover space

    def render(self, stdscr, rect: Rect, ctx) -> None: ...
    def handle_key(self, ch: int) -> KeyResult: ...


class Spacer:
    """Invisible filler."""
    min_w = 0
    min_h = 0
    flex = 1

    def render(self, stdscr, rect: Rect, ctx) -> None:
        pass

    def handle_key(self, ch: int) -> KeyResult:
        return KeyResult.IGNORED


# Max sprite dimensions (see species.py art): 6 rows + optional overlay row = 7.
# Width is up to 20. Box adds 2 cols of padding.
_BUDDY_BOX_W = 22
_BUDDY_BOX_H = 7 + 2  # sprite + header + status


class BuddyBoxSlot:
    """Renders the buddy sprite + header + status in a fixed column.

    The slot also owns bubble rendering (anchored above the sprite inside
    this slot). If the bubble's requested height would exceed the slot,
    draw_bubble already handles falling back / wrapping gracefully.
    """
    min_w = _BUDDY_BOX_W
    min_h = _BUDDY_BOX_H
    flex = 0

    def render(self, stdscr, rect: Rect, ctx) -> None:
        if rect.w <= 0 or rect.h <= 0 or ctx is None:
            return
        sprite = ctx.sprite
        sprite_h = len(sprite)
        sprite_w = max((len(l) for l in sprite), default=0)

        # Center the sprite horizontally inside the slot, pin to top.
        sprite_x = rect.x + max(0, (rect.w - sprite_w) // 2)
        sprite_y = rect.y

        for i, line in enumerate(sprite):
            if sprite_y + i >= rect.y + rect.h:
                break
            try:
                stdscr.addstr(sprite_y + i, sprite_x, line[: rect.w], ctx.attr)
            except curses.error:
                pass

        # Header + status occupy the two rows below the sprite, centered in slot width.
        header_y = sprite_y + sprite_h
        status_y = header_y + 1
        if header_y < rect.y + rect.h:
            self._center_line(stdscr, header_y, rect, ctx.header_text, ctx.attr)
        if status_y < rect.y + rect.h:
            self._center_line(stdscr, status_y, rect, ctx.status_text, curses.A_DIM)

        # Bubble stacks above the slot, matching the box width so it stays aligned.
        if ctx.bubble_text:
            draw_bubble(stdscr, rect, ctx.bubble_text, ctx.attr)

    def handle_key(self, ch: int) -> KeyResult:
        return KeyResult.IGNORED

    @staticmethod
    def _center_line(stdscr, y: int, rect: Rect, text: str, attr) -> None:
        if not text or rect.w <= 0:
            return
        if len(text) > rect.w:
            text = text[: max(0, rect.w - 1)] + "…" if rect.w > 1 else text[: rect.w]
        x = rect.x + max(0, (rect.w - len(text)) // 2)
        try:
            stdscr.addstr(y, x, text, attr)
        except curses.error:
            pass


def layout_slots(slots: list[PromptSlot], rect: Rect) -> list[Rect]:
    """Lay out slots left-to-right inside `rect`.

    Fixed-width slots (flex == 0) get min_w columns. Remaining space is split
    proportionally by `flex` among flexing slots. Slots that don't fit are
    given an empty rect (caller can detect via w <= 0).
    """
    if rect.h <= 0 or rect.w <= 0 or not slots:
        return [Rect(rect.y, rect.x, 0, 0) for _ in slots]

    fixed = sum(s.min_w for s in slots if s.flex == 0)
    total_flex = sum(s.flex for s in slots if s.flex > 0)
    leftover = max(0, rect.w - fixed)

    rects: list[Rect] = []
    x = rect.x
    for s in slots:
        if s.flex == 0:
            w = min(s.min_w, max(0, rect.x + rect.w - x))
        elif total_flex > 0:
            w = (leftover * s.flex) // total_flex
        else:
            w = 0
        rects.append(Rect(y=rect.y, x=x, h=rect.h, w=w))
        x += w
    return rects


def draw_prompt_area(stdscr, rect: Rect, slots: list[PromptSlot], ctx) -> None:
    if rect.h <= 0 or not slots:
        return
    for slot, slot_rect in zip(slots, layout_slots(slots, rect)):
        if slot_rect.w <= 0 or slot_rect.h <= 0:
            continue
        slot.render(stdscr, slot_rect, ctx)
