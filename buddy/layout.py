"""Layout math for the buddy renderer.

All screen position/size calculations live here. `compute_layout` runs once
at startup and again on resize; every region renderer takes the rect it owns.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Rect:
    y: int
    x: int
    h: int
    w: int


@dataclass
class Layout:
    sprite: Rect   # sprite block (sprite_h rows, sprite_w cols)
    header: Rect   # one line below sprite
    status: Rect   # two lines below sprite
    prompt: Rect   # bottom strip for PromptSlot widgets (h=0 when empty)
    hint: Rect     # bottom-right "q to quit"
    # bubble is self-sizing; it anchors to `sprite` (see regions.draw_bubble)


def compute_layout(h: int, w: int, sprite_h: int, sprite_w: int, prompt_h: int = 0) -> Layout:
    # Reserve the bottom `prompt_h` rows for slot widgets (plus the hint row).
    # Everything else (sprite + header + status) centers in the remaining space.
    usable_h = max(0, h - prompt_h)
    start_y = max(0, (usable_h - sprite_h - 4) // 2)
    start_x = max(0, (w - sprite_w) // 2)
    footer_y = min(usable_h - 2 if usable_h >= 2 else 0, start_y + sprite_h + 1)
    prompt_y = h - prompt_h - 1  # one row above the hint line
    return Layout(
        sprite=Rect(y=start_y, x=start_x, h=sprite_h, w=sprite_w),
        header=Rect(y=footer_y, x=0, h=1, w=w),
        status=Rect(y=footer_y + 1, x=0, h=1, w=w),
        prompt=Rect(y=prompt_y, x=0, h=prompt_h, w=w),
        hint=Rect(y=h - 1, x=0, h=1, w=w),
    )
