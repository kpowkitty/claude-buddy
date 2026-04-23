"""Hatch animation overlay — a bordered box that pops up when a buddy hatches.

Owns the hatch itself: the caller passes a trigger ("tokens" or "shards")
and the overlay performs the roll at CRACK_END so the persisted switch
lines up with the visible shell breaking. The new buddy is NOT made
active (set_active=False) so the habitat doesn't flip to the new pet
mid-animation — the user returns to the gacha menu afterward and can
choose to switch manually. Exception: if the roster was empty before the
hatch, the new buddy becomes active (nothing to be surprised by).

Phases (10fps):
  idle   → egg sits, rarity-tinted
  shake  → egg rocks left/right
  crack  → three progressive crack frames (hatch writes to disk here)
  reveal → rarity banner + sprite + name + flavor + skill bars; stays
           until the user presses q

Renders a rarity-tinted border around the animation; the modal screen's
background is transparent, so the pty and habitat remain visible around
the box.

Dismiss payload: ("hatched", entry_or_None). q only works once the reveal
has landed — no skipping past the ceremony.
"""
from __future__ import annotations

import os
import random
import sys
import textwrap
from typing import Optional

from rich.segment import Segment
from rich.style import Style
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widget import Widget

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUDDY = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
if _BUDDY not in sys.path:
    sys.path.insert(0, _BUDDY)

import hatch as _hatch  # noqa: E402
from collection import all_buddies, migrate  # noqa: E402
from species import RARITY_ORDER, SKILLS, SPECIES, find_species  # noqa: E402
from sprites import frames_for  # noqa: E402
from state import PROGRESSION, read_json  # noqa: E402


_RARITY_COLOR = {
    "common": "white",
    "uncommon": "green",
    "rare": "blue",
    "epic": "magenta",
    "legendary": "yellow",
}


# ── egg art ──────────────────────────────────────────────────────────────
# Seven-row egg. Kept local (not in sprites.py) because sprites.py is keyed
# by species_id/mood and an egg is neither.

_EGG_IDLE = [
    "   .-=-.   ",
    "  /     \\  ",
    " |       | ",
    " |       | ",
    " |       | ",
    "  \\     /  ",
    "   '---'   ",
]

# Shake: same rows shifted one column. A blank col on one side balances it.
_EGG_SHAKE_L = [" " + line[:-1] if line.strip() else line for line in _EGG_IDLE]
_EGG_SHAKE_R = [line[1:] + " " if line.strip() else line for line in _EGG_IDLE]

_EGG_CRACK_1 = [
    "   .-=-.   ",
    "  /     \\  ",
    " |    /  | ",
    " |   /   | ",
    " |       | ",
    "  \\     /  ",
    "   '---'   ",
]

_EGG_CRACK_2 = [
    "   .-=-.   ",
    "  /  ,  \\  ",
    " |  /\\/  | ",
    " |  \\/\\  | ",
    " |   /   | ",
    "  \\ /   /  ",
    "   '---'   ",
]

_EGG_CRACK_3 = [
    "   . - .   ",
    "  /\\   \\/  ",
    " |  \\_/  | ",
    " |       | ",
    "  \\_/ \\_/  ",
    "  '     '  ",
    "   . . .   ",
]


def _pick_frame(tick: int, idle_end: int, shake_end: int, crack_end: int) -> list[str]:
    """Return the egg-phase frame for the given tick. Reveal phase is handled
    separately because it paints species sprite + banner, not just an egg."""
    if tick < idle_end:
        return _EGG_IDLE
    if tick < shake_end:
        # Flip left/right every 2 ticks for a visible rock.
        return _EGG_SHAKE_L if ((tick // 2) % 2 == 0) else _EGG_SHAKE_R
    # Crack phase spans crack_end - shake_end ticks; carve it into thirds.
    span = crack_end - shake_end
    progress = tick - shake_end
    third = span // 3 if span >= 3 else 1
    if progress < third:
        return _EGG_CRACK_1
    if progress < 2 * third:
        return _EGG_CRACK_2
    return _EGG_CRACK_3


def _skill_bars(skills: dict, signature: str | None) -> list[str]:
    """Eight rows of `name  [█..░]  NN ★`, mirroring hatch.render_reveal."""
    width = max(len(s) for s in SKILLS)
    out = []
    for skill in SKILLS:
        value = int(skills.get(skill, 0))
        bar_len = 20
        filled = int(round(value / 100 * bar_len))
        bar = "█" * filled + "░" * (bar_len - filled)
        marker = " ★" if skill == signature else "  "
        out.append(f"{skill.ljust(width)}  {bar}  {value:3d}{marker}")
    return out


# Box inner dims need to fit the widest reveal line. Skill row width =
# 13 (longest skill name) + 2 + 20 + 2 + 3 + 2 ≈ 42. Height = banner(1) +
# blank + sprite(~7) + blank + name(1) + flavor(1) + blank + 8 skills = ~20.
# Add some slack so species with taller art (cephalo is 7) still fit.
_BOX_INNER_W = 48
_BOX_INNER_H = 22


class _HatchStage(Widget):
    """Paints a bordered box containing the current phase.

    Sized exactly to the box dimensions so the rest of the screen stays
    untouched and the underlying pty / habitat show through the ModalScreen's
    transparent background.
    """

    DEFAULT_CSS = f"""
    _HatchStage {{
        width: {_BOX_INNER_W + 2};
        height: {_BOX_INNER_H + 2};
    }}
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tick = 0

    def set_tick(self, tick: int) -> None:
        self._tick = tick
        self.refresh()

    def _lines(self) -> tuple[list[str], Style]:
        """Compose the block of text to draw and the style to tint it with."""
        screen: "HatchOverlay" = self.screen  # type: ignore[assignment]
        tick = self._tick
        rarity = screen._rarity
        color = _RARITY_COLOR.get(rarity, "white")
        bold = rarity in ("epic", "legendary")
        base_style = Style(color=color, bold=bold)

        if tick >= screen.CRACK_END:
            # Reveal phase — stays up until the user presses q.
            block = screen._reveal_block()
            return block, base_style

        egg = _pick_frame(tick, screen.IDLE_END, screen.SHAKE_END, screen.CRACK_END)
        return list(egg), base_style

    def render_line(self, y: int) -> Strip:
        w = self.size.width
        h = self.size.height
        inner_w = w - 2
        inner_h = h - 2

        screen: "HatchOverlay" = self.screen  # type: ignore[assignment]
        rarity = screen._rarity
        border_color = _RARITY_COLOR.get(rarity, "white")
        bold_border = rarity in ("epic", "legendary")
        border_style = Style(color=border_color, bold=bold_border)

        # Prepare wrapped content and scroll state to know whether to show
        # the ▲/▼ indicators on the top/bottom border rows.
        lines, content_style = self._lines()
        wrapped = self._wrap_block(lines, inner_w)
        overflow = max(0, len(wrapped) - inner_h)
        scroll_y = min(screen._scroll_y, overflow) if overflow else 0
        can_scroll_up = scroll_y > 0
        can_scroll_down = scroll_y < overflow

        if y == 0:
            # ▲ indicator slots into the top rule when the view is scrolled.
            bar = "─" * (w - 2)
            if can_scroll_up:
                mid = (len(bar) - 3) // 2
                bar = "─" * mid + " ▲ " + "─" * (len(bar) - mid - 3)
            edge = "╭" + bar + "╮"
            return Strip([Segment(edge, border_style)])
        if y == h - 1:
            # Footer hint + ▼ indicator share the bottom rule.
            hint = "  press q to continue  " if screen._dismissable else ""
            bar = "─" * (w - 2)
            if hint and len(hint) + 4 <= w - 2:
                pad = (len(bar) - len(hint)) // 2
                bar = "─" * pad + hint + "─" * (len(bar) - pad - len(hint))
            if can_scroll_down:
                # Drop ▼ onto the right side of the bar, leaving the hint
                # centered.
                idx = len(bar) - 4
                if idx > 0:
                    bar = bar[:idx] + " ▼ " + bar[idx + 3:]
            edge = "╰" + bar + "╯"
            return Strip([Segment(edge, border_style)])

        inner_y = y - 1

        # During the egg/reveal phases the content block is centered; for
        # long revealed blocks that overflow, we anchor at the top and let
        # the user scroll instead of centering.
        if wrapped and len(wrapped) <= inner_h:
            top = max(0, (inner_h - len(wrapped)) // 2)
            source_y = inner_y - top
            in_range = 0 <= source_y < len(wrapped)
        else:
            source_y = inner_y + scroll_y
            in_range = 0 <= source_y < len(wrapped)

        if in_range:
            line = wrapped[source_y]
            # Clip to inner_w so overflow never eats the right border, and
            # center the line horizontally within the box.
            if len(line) > inner_w:
                line = line[:inner_w]
            pad_left = max(0, (inner_w - len(line)) // 2)
            pad_right = inner_w - pad_left - len(line)
            interior = [
                Segment(" " * pad_left, Style()),
                Segment(line, content_style),
                Segment(" " * pad_right, Style()),
            ]
        else:
            interior = [Segment(" " * inner_w, Style())]

        return Strip(
            [Segment("│", border_style)] + interior + [Segment("│", border_style)]
        )

    def _wrap_block(self, lines: list[str], inner_w: int) -> list[str]:
        """Expand any line wider than inner_w into multiple wrapped lines.

        Preserves short lines (sprite art, skill rows, the star banner) as-is
        so fixed-width art doesn't get mangled. Only long prose lines like
        the flavor text actually reflow.
        """
        if inner_w <= 0:
            return list(lines)
        out: list[str] = []
        for line in lines:
            if len(line) <= inner_w:
                out.append(line)
                continue
            wrapped = textwrap.wrap(
                line,
                width=inner_w,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
                drop_whitespace=False,
            ) or [line[:inner_w]]
            out.extend(wrapped)
        return out


class HatchOverlay(ModalScreen):
    """Bordered hatch ceremony. Owns the hatch roll itself.

    Args:
        trigger: "tokens" or "shards" — which economy path to roll on.
        rng: optional seeded Random for deterministic tests.

    Dismiss payload is ("hatched", entry_or_None). entry is None on a
    duplicate token roll (the overlay still shows the dup species with a
    +1 shard note). On refused rolls (no token / not enough shards), the
    overlay never mounts — the caller checks preconditions first.
    """

    # Phase boundaries, in 10fps ticks. Exposed as class attrs so tests can
    # shrink them without monkeypatching internals.
    IDLE_END = 8
    SHAKE_END = 18
    CRACK_END = 28

    # q is the only dismiss, and only after the reveal lands. enter/space
    # are intentionally NOT bound — we don't want a careless keystroke to
    # skip the ceremony. ↑/↓ scroll the reveal content for species whose
    # flavor wraps or whose skill bars overflow the box height.
    BINDINGS = [
        Binding("q", "close", "Close", show=True),
        Binding("up", "scroll(-1)", "↑", show=False),
        Binding("down", "scroll(1)", "↓", show=False),
        Binding("pageup", "scroll(-5)", "PgUp", show=False),
        Binding("pagedown", "scroll(5)", "PgDn", show=False),
    ]

    # Transparent background: ModalScreen would otherwise dim the app
    # underneath (`background: $background 60%`). Setting it to transparent
    # makes Textual defer to the base screen's render, so the pty and
    # habitat show through everywhere the stage isn't painting.
    DEFAULT_CSS = """
    HatchOverlay {
        align: center middle;
        background: transparent;
    }
    """

    def __init__(
        self,
        trigger: str,
        *,
        rng: random.Random | None = None,
    ) -> None:
        super().__init__()
        if trigger not in ("tokens", "shards"):
            raise ValueError(f"unknown hatch trigger: {trigger!r}")
        self._trigger = trigger
        self._rng = rng
        self._tick = 0
        self._done = False
        self._hatched = False
        self._dismissable = False
        self._scroll_y = 0
        self._timer = None

        # Pre-fill with neutral defaults so the idle/shake phases have
        # something to paint. The actual species/rarity is determined at
        # CRACK_END; we update these fields then.
        self._rarity: str = "common"
        self._species_id: str = ""
        self._species_name: str = "???"
        self._flavor: str = ""
        self._skills: dict = {}
        self._signature: Optional[str] = None
        self._entry: Optional[dict] = None
        self._is_dupe: bool = False
        self._result_message: str = ""

    def compose(self) -> ComposeResult:
        yield _HatchStage(id="hatch-stage")

    def on_mount(self) -> None:
        self._timer = self.set_interval(1 / 10, self._advance)

    # ── tick loop ───────────────────────────────────────────────────────

    def _advance(self) -> None:
        if self._done:
            return
        self._tick += 1
        if self._tick == self.CRACK_END:
            # Hatch happens exactly as the shell finishes breaking.
            self._perform_hatch()
            self._dismissable = True
        stage = self.query_one("#hatch-stage", _HatchStage)
        stage.set_tick(self._tick)
        # Footer hint needs a repaint when _dismissable flips — the stage
        # refresh above only redraws the stage body; the bottom border is
        # part of the same widget, so it'll be picked up.

    # ── hatch (called at CRACK_END) ─────────────────────────────────────

    def _perform_hatch(self) -> None:
        if self._hatched:
            return
        self._hatched = True

        # Roster-was-empty check: if there are no buddies yet, the new
        # buddy becomes active automatically. There's nothing on-screen
        # to be surprised by.
        raw = read_json(PROGRESSION, None)
        was_empty = True
        if raw is not None:
            try:
                was_empty = len(all_buddies(migrate(raw))) == 0
            except Exception:
                was_empty = True
        set_active = was_empty

        if self._trigger == "tokens":
            ok, msg, entry = _hatch.spend_token_hatch(self._rng, set_active=set_active)
        else:
            ok, msg, entry = _hatch.redeem_shards_hatch(self._rng, set_active=set_active)

        self._result_message = msg or ""
        if not ok:
            # Shouldn't happen: caller is expected to pre-check. Degrade
            # gracefully with a minimal error reveal.
            self._rarity = "common"
            self._species_name = "No hatch"
            self._flavor = msg or "refused"
            return

        if entry is None:
            # Duplicate token roll. Pull the dup species_id out of the
            # collection so we can show its art + rarity in the reveal.
            self._is_dupe = True
            species_id = self._guess_dupe_species_id(msg)
            rarity, species = find_species(species_id) if species_id else (None, None)
            if species:
                self._rarity = rarity or "common"
                self._species_id = species["id"]
                self._species_name = species["name"]
                self._flavor = species.get("flavor", "")
                self._signature = species.get("signature")
            return

        # New species.
        self._entry = entry
        self._rarity = str(entry.get("rarity") or "common")
        self._species_id = str(entry.get("species_id") or "")
        self._species_name = str(entry.get("species_name") or self._species_id or "???")
        self._flavor = str(entry.get("flavor") or "")
        self._skills = dict(entry.get("skills") or {})
        self._signature = entry.get("signature_skill")

    def _guess_dupe_species_id(self, msg: str) -> str | None:
        """Duplicate messages are `"<Name> — duplicate! +1 shard."`.
        Try to recover the species_id by matching the name back to SPECIES."""
        if not msg:
            return None
        name = msg.split(" — ")[0].strip()
        for rarity in RARITY_ORDER:
            for sp in SPECIES[rarity]:
                if sp["name"] == name:
                    return sp["id"]
        return None

    # ── dismiss ─────────────────────────────────────────────────────────

    def action_close(self) -> None:
        # Locked until the reveal lands. The binding will still fire
        # during the animation; we just ignore it.
        if not self._dismissable:
            return
        self._finish()

    def action_scroll(self, delta: int) -> None:
        """Scroll the reveal content by `delta` rows. No-op until the
        reveal has landed — there's nothing to scroll during the egg
        animation phases."""
        if not self._dismissable:
            return
        self._scroll_y = max(0, self._scroll_y + delta)
        stage = self.query_one("#hatch-stage", _HatchStage)
        stage.refresh()

    def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None
        self.dismiss(("hatched", self._entry))

    # ── reveal content ──────────────────────────────────────────────────

    def _reveal_block(self) -> list[str]:
        """Full reveal: ★ banner, sprite, name, flavor, skill bars (or
        a +1 shard note for duplicates)."""
        block: list[str] = []
        # Banner: "★ COMMON ★" for fresh hatches, "⚠ DUPE! ⚠" for dupes so
        # the outcome is obvious at a glance before the user reads on.
        if self._is_dupe:
            block.append("⚠ DUPE! ⚠")
        else:
            block.append(f"★ {self._rarity.upper()} ★")
        block.append("")
        for line in self._reveal_sprite():
            block.append(line)
        block.append("")
        if self._is_dupe:
            block.append(f"already had a {self._species_name}")
            block.append("+1 shard toward a guaranteed new species")
        else:
            block.append(self._species_name)
            if self._flavor:
                block.append(self._flavor)
            if self._skills:
                block.append("")
                for bar in _skill_bars(self._skills, self._signature):
                    block.append(bar)
        return block

    def _reveal_sprite(self) -> list[str]:
        """Pick the sprite to show at reveal time. Falls back gracefully if
        frames_for returns nothing usable."""
        if not self._species_id:
            return ["?"]
        try:
            frames = frames_for(self._species_id, "celebrating")
        except Exception:
            frames = None
        if frames:
            frame = frames[0]
            if frame:
                return list(frame)
        _, species = find_species(self._species_id)
        if species and species.get("art"):
            return list(species["art"])
        return ["?"]
