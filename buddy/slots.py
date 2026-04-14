"""Prompt-area plug-in surface.

The prompt area (bottom strip of the buddy window) is a row of `PromptSlot`
widgets laid out left-to-right. Adding a feature (input, buddy-in-a-box, mood
badge, rarity meter, tool indicator) is a matter of writing a new slot class
and registering it — no layout or renderer changes required.

v1 only ships `Spacer`, which draws nothing. This proves the plumbing without
changing what the user sees. `InputSlot` and `BuddyBoxSlot` land with the
mini Claude terminal feature.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from input import KeyResult
from layout import Rect


@runtime_checkable
class PromptSlot(Protocol):
    min_w: int   # minimum columns required; 0 means "none"
    min_h: int   # minimum rows required
    flex: int    # 0 = fixed width, >0 = share of leftover space

    def render(self, stdscr, rect: Rect, ctx) -> None: ...
    def handle_key(self, ch: int) -> KeyResult: ...


class Spacer:
    """Invisible filler. v1 default so the prompt area exists but draws nothing."""
    min_w = 0
    min_h = 0
    flex = 1

    def render(self, stdscr, rect: Rect, ctx) -> None:
        pass

    def handle_key(self, ch: int) -> KeyResult:
        return KeyResult.IGNORED


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
