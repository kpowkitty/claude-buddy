"""Habitat — the buddy's side panel in the Textual app.

Right-side column (~24 cols wide) containing sprite, name, mood, XP, skills,
activity feed, time-with-buddy. All widgets consume a BuddyView snapshot
produced by state_adapter; they never touch the JSON files themselves.

Structure is intentionally composable: each sub-widget is a self-contained
Widget subclass. Adding a new panel = write a class + mount it in Habitat.
"""
from __future__ import annotations

import os
import sys
from typing import Optional

from rich.segment import Segment
from rich.style import Style
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.strip import Strip
from textual.widget import Widget

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUDDY = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _BUDDY)

from state_adapter import BuddyView, read_view  # noqa: E402
from species import find_species, SKILLS  # noqa: E402
from sprites import frames_for  # noqa: E402


HABITAT_WIDTH = 24
_POLL_HZ = 3  # state.json polling rate; Hz

# Textual 8.2.3 loses alpha when converting Color → Rich Style (rich_color
# discards the alpha channel), so `background: rgba(0,0,0,0)` still paints
# opaque black at render time. The workaround is to skip Widget.render_line's
# default Strip.blank(..., visual_style.rich_style) and emit a Strip whose
# Segment style has bgcolor=None — which IS transparent in Rich.
_TRANSPARENT_BLANK_STYLE = Style()  # no fg, no bg → terminal default shows through


def _transparent_blank_line(width: int) -> Strip:
    return Strip([Segment(" " * width, _TRANSPARENT_BLANK_STYLE)])

_RARITY_COLOR = {
    "common": "white",
    "uncommon": "green",
    "rare": "blue",
    "epic": "magenta",
    "legendary": "yellow",
}


# ──────────────────────────────────────────────────────────────────────────
# Sub-widgets


class SpritePanel(Widget):
    """Renders the 3-line sprite, animated by mood + activity."""

    DEFAULT_CSS = """
    SpritePanel {
        height: 7;
        content-align: center middle;
    }
    """

    view: reactive[Optional[BuddyView]] = reactive(None, layout=False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tick = 0
        self.set_interval(1 / 10, self._advance)  # 10fps animation

    def _advance(self) -> None:
        self._tick += 1
        self.refresh()

    def render_line(self, y: int) -> Strip:
        w = self.size.width
        blank = Strip([Segment(" " * w, Style())])
        v = self.view
        if v is None or not v.has_buddy or not v.species_id:
            return blank
        rarity, species = find_species(v.species_id)
        if species is None:
            return blank
        frames = frames_for(v.species_id, v.mood)
        # Animation cadence matches buddy/buddy.py: idle blink every 25s,
        # sleeping slow, others ~0.5s.
        if v.mood == "idle":
            cycle = self._tick % 250
            idx = 1 if cycle < 2 else 0
        elif v.mood == "sleeping":
            idx = (self._tick // 10) % 2
        else:
            # More active = faster blinks. activity_rate is 0..1.
            # Period doubled vs. original so the tail wag reads as a
            # gentle swish rather than a frantic blur.
            period = max(4, int(20 - v.activity_rate * 14))
            idx = (self._tick // period) % 2
        sprite = frames[idx]
        if y >= len(sprite):
            return blank
        line = sprite[y]
        color = _RARITY_COLOR.get(rarity or "common", "white")
        bold = rarity in ("epic", "legendary")
        style = Style(color=color, bold=bold)
        # Center within widget width.
        line_w = len(line)
        pad_left = max(0, (w - line_w) // 2)
        pad_right = max(0, w - pad_left - line_w)
        return Strip([
            Segment(" " * pad_left, Style()),
            Segment(line, style),
            Segment(" " * pad_right, Style()),
        ])


class NamePanel(Widget):
    """★ Name ★ line under the sprite."""

    DEFAULT_CSS = """
    NamePanel { height: 1; }
    """

    view: reactive[Optional[BuddyView]] = reactive(None)
    _text: reactive[str] = reactive("")

    def watch_view(self, view: Optional[BuddyView]) -> None:
        if view is None or not view.has_buddy:
            self._text = ""
            self.refresh()
            return
        name = view.name or (view.species_id or "buddy").title()
        self._text = f"★ {name} ★"
        self.refresh()

    def render_line(self, y: int) -> Strip:
        w = self.size.width
        if y != 0 or not self._text:
            return _transparent_blank_line(w)
        pad = max(0, w - len(self._text))
        pl = pad // 2
        pr = pad - pl
        return Strip([
            Segment(" " * pl, _TRANSPARENT_BLANK_STYLE),
            Segment(self._text, Style(bold=True)),
            Segment(" " * pr, _TRANSPARENT_BLANK_STYLE),
        ])


class XPBar(Widget):
    """Horizontal bar: current level progress."""

    DEFAULT_CSS = """
    XPBar { height: 2; }
    """

    view: reactive[Optional[BuddyView]] = reactive(None, layout=False)

    _INSET = 1  # cells of breathing room on each side of the bar

    def render_line(self, y: int) -> Strip:
        w = self.size.width
        v = self.view
        if v is None or not v.has_buddy:
            return Strip([Segment(" " * w, Style())])
        inset = self._INSET
        bar_w = max(1, w - inset * 2)
        gutter = Segment(" " * inset, Style())
        if y == 0:
            label = f"lvl {v.level}  xp {v.xp}"
            pad = max(0, bar_w - len(label))
            return Strip([
                gutter,
                Segment(label, Style(color="bright_cyan")),
                Segment(" " * pad, Style()),
                gutter,
            ])
        # Bar row: progress within current level.
        this_level_start = (v.level ** 2) * 10
        next_level_start = ((v.level + 1) ** 2) * 10
        denom = max(1, next_level_start - this_level_start)
        progress = (v.xp - this_level_start) / denom
        progress = max(0.0, min(1.0, progress))
        filled = int(progress * bar_w)
        return Strip([
            gutter,
            Segment("█" * filled, Style(color="bright_cyan")),
            Segment("░" * (bar_w - filled), Style(color="cyan")),
            gutter,
        ])


class SkillGrid(Widget):
    """Mini bars for each of the 8 skills in species.SKILLS."""

    DEFAULT_CSS = """
    SkillGrid { height: 8; }
    """

    view: reactive[Optional[BuddyView]] = reactive(None, layout=False)

    def render_line(self, y: int) -> Strip:
        w = self.size.width
        v = self.view
        if v is None or not v.has_buddy or y >= len(SKILLS):
            return Strip([Segment(" " * w, Style())])
        skill = SKILLS[y]
        score = int(v.skills.get(skill, 0))
        score = max(0, min(100, score))
        # Label: first 4 chars of skill name, padded to 5.
        label = skill[:4].ljust(5)
        bar_w = max(1, w - len(label) - 5)  # room for "  NN"
        filled = int((score / 100) * bar_w)
        is_signature = skill == v.signature_skill
        bar_color = "bright_yellow" if is_signature else "green"
        return Strip([
            Segment(label, Style(color="bright_white" if is_signature else "white")),
            Segment("▰" * filled, Style(color=bar_color)),
            Segment("▱" * (bar_w - filled), Style(color="grey37")),
            Segment(f" {score:>3}", Style(color="white")),
        ])


class Bubble(Widget):
    """Speech bubble rendered above the sprite when buddy chirps.

    Self-sizing in height: as tall as needed to fit wrapped text. When
    `view.speech` is None, the widget collapses to height 0 so the sprite
    sits flush against whatever's above.
    """

    DEFAULT_CSS = """
    Bubble {
        height: auto;
        max-height: 10;
    }
    """

    view: reactive[Optional[BuddyView]] = reactive(None, layout=True)

    def watch_view(self, view: Optional[BuddyView]) -> None:
        # Force a re-layout so our height: auto recomputes.
        self.refresh(layout=True)

    def render_line(self, y: int) -> Strip:
        w = self.size.width
        blank = Strip([Segment(" " * w, Style())])
        v = self.view
        if v is None or not v.speech:
            return blank
        lines = self._compose_lines(v.speech, w)
        if y >= len(lines):
            return blank
        return Strip([Segment(lines[y].ljust(w), Style(color="cyan"))])

    def get_content_height(self, container, viewport, width: int) -> int:
        v = self.view
        if v is None or not v.speech:
            return 0
        return len(self._compose_lines(v.speech, width))

    @staticmethod
    def _compose_lines(text: str, w: int) -> list[str]:
        inner_w = max(1, w - 4)  # borders + padding
        if inner_w <= 0:
            return []
        # Word-wrap to inner_w.
        words = text.split()
        wrapped: list[str] = []
        cur = ""
        for word in words:
            if not cur:
                cur = word[:inner_w]
            elif len(cur) + 1 + len(word) <= inner_w:
                cur = cur + " " + word
            else:
                wrapped.append(cur)
                cur = word[:inner_w]
        if cur:
            wrapped.append(cur)
        if not wrapped:
            return []
        box_w = w
        inner = box_w - 2
        top = "╭" + "─" * (box_w - 2) + "╮"
        bot = "╰" + "─" * (box_w - 2) + "╯"
        body = ["│" + line.center(inner) + "│" for line in wrapped]
        # Tail below the bubble, centered under the box.
        tail = " " * (box_w // 2) + "▼" + " " * (box_w - box_w // 2 - 1)
        return [top, *body, bot, tail]


class TimeWithBuddy(Widget):
    """'with you for 3d 14h' line at bottom."""

    DEFAULT_CSS = """
    TimeWithBuddy { height: 1; }
    """

    view: reactive[Optional[BuddyView]] = reactive(None)
    _text: reactive[str] = reactive("")

    def watch_view(self, view: Optional[BuddyView]) -> None:
        if view is None or not view.has_buddy or view.time_with_buddy_s <= 0:
            self._text = ""
        else:
            self._text = _fmt_duration(view.time_with_buddy_s)
        self.refresh()

    def render_line(self, y: int) -> Strip:
        w = self.size.width
        if y != 0 or not self._text:
            return _transparent_blank_line(w)
        pad = max(0, w - len(self._text))
        pl = pad // 2
        pr = pad - pl
        return Strip([
            Segment(" " * pl, _TRANSPARENT_BLANK_STYLE),
            Segment(self._text, Style(color="grey50")),
            Segment(" " * pr, _TRANSPARENT_BLANK_STYLE),
        ])


def _fmt_duration(s: int) -> str:
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    if d:
        return f"with you {d}d {h}h"
    if h:
        return f"with you {h}h {m}m"
    if m:
        return f"with you {m}m"
    return f"with you {s}s"


# ──────────────────────────────────────────────────────────────────────────
# Container


class _TransparentSpacer(Widget):
    """A flex spacer that paints no background.

    Using a plain Static("") for the spacer causes Widget.render_line to
    fall through to Strip.blank(..., visual_style.rich_style) — and because
    Textual 8.2.3's Color→rich_color conversion discards alpha, that paints
    opaque black regardless of our `background: rgba(0,0,0,0)` CSS.
    """

    DEFAULT_CSS = """
    _TransparentSpacer { height: 1fr; }
    """

    def render_line(self, y: int) -> Strip:
        return _transparent_blank_line(self.size.width)


class Habitat(Vertical):
    """Composes all sub-widgets into a single right-side panel.

    Layout is bottom-aligned: a flexible spacer at the top pushes the sprite
    + name + status + xp + (skills) + time to the bottom of the column.
    Speech bubble appears above the sprite when buddy chirps.
    """

    DEFAULT_CSS = f"""
    Habitat {{
        width: {HABITAT_WIDTH};
        height: 100%;
        background: rgba(0, 0, 0, 0);
        padding: 0 1;
    }}
    Habitat > * {{
        background: rgba(0, 0, 0, 0);
    }}
    Habitat > #skills.hidden {{
        display: none;
    }}
    """

    def compose(self) -> ComposeResult:
        yield _TransparentSpacer(id="spacer")
        yield Bubble(id="bubble")
        yield SpritePanel(id="sprite")
        yield NamePanel(id="name")
        yield XPBar(id="xp")
        skills = SkillGrid(id="skills")
        skills.add_class("hidden")
        yield skills
        yield TimeWithBuddy(id="time")

    def render_line(self, y: int) -> Strip:
        return _transparent_blank_line(self.size.width)

    def on_mount(self) -> None:
        self.set_interval(1 / _POLL_HZ, self._refresh_view)

    def toggle_skills(self) -> None:
        self.query_one("#skills", SkillGrid).toggle_class("hidden")

    def _refresh_view(self) -> None:
        view = read_view()
        self.query_one("#sprite", SpritePanel).view = view
        self.query_one("#name", NamePanel).view = view
        self.query_one("#xp", XPBar).view = view
        self.query_one("#skills", SkillGrid).view = view
        self.query_one("#time", TimeWithBuddy).view = view
        self.query_one("#bubble", Bubble).view = view
