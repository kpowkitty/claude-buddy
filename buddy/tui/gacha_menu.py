"""Gacha collection menu — the F2 modal overlay.

Shows every species in the roster, grouped by rarity, with filled slots
for buddies the user owns and placeholder slots for the rest. Arrow keys
navigate filled slots; Enter switches to the highlighted buddy; H (or a
click on the banner) spends 5 shards for a guaranteed-new hatch.

Reads progression via collection.read_collection; writes via
switch.switch_to and hatch.redeem_shards_hatch so the economy rules live
in one place.
"""
from __future__ import annotations

import sys
from pathlib import Path

from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static

# Reach back to buddy/*.py.
_HERE = Path(__file__).resolve().parent
_BUDDY = _HERE.parent
if str(_BUDDY) not in sys.path:
    sys.path.insert(0, str(_BUDDY))

from collection import (  # noqa: E402
    SHARDS_PER_REDEEM,
    _buddy_level,
    all_buddies,
    global_level,
    hatches_available,
    migrate,
    shards,
)
import hatch as _hatch  # noqa: E402
from hatch_overlay import HatchOverlay  # noqa: E402
from message_box import MessageBox  # noqa: E402
from species import RARITY_ORDER, SPECIES, find_species  # noqa: E402
from sprites import frames_for  # noqa: E402
from state import PROGRESSION, read_json  # noqa: E402
import switch as _switch  # noqa: E402


class _CursorDrivenScroll(VerticalScroll, inherit_bindings=False):
    """VerticalScroll without ScrollableContainer's arrow-key bindings.

    ScrollableContainer binds up/down/left/right to scroll actions. A
    plain `BINDINGS = []` override doesn't suppress them because Textual
    merges bindings up the class chain by default — we need
    `inherit_bindings=False` to actually drop them. Cursor navigation
    lives entirely on the modal; this container just paints.
    """

    BINDINGS: list = []

_RARITY_COLOR = {
    "common": "white",
    "uncommon": "green",
    "rare": "blue",
    "epic": "magenta",
    "legendary": "yellow",
}


def _load_collection() -> dict:
    raw = read_json(PROGRESSION, {}) or {}
    return migrate(raw)


class _Slot(Widget, can_focus=True):
    """One cell in the collection grid. Represents a species: either
    filled (user owns one) or empty (they don't yet).

    Public state:
      - species_id: the species this slot represents (always set).
      - filled: True if the user owns this species.
      - entry: the buddy dict if filled, else None.
      - selected: True if this slot is the cursor target.
    """

    DEFAULT_CSS = """
    _Slot {
        width: 1fr;
        height: 9;
        padding: 0 1;
        content-align: center middle;
    }
    """

    def __init__(self, species_id: str, entry: dict | None, *, active: bool, **kwargs) -> None:
        super().__init__(**kwargs)
        self.species_id = species_id
        self.entry = entry
        self.filled = entry is not None
        self.active = active
        self.selected = False

    def render_line(self, y: int) -> Strip:
        w = self.size.width
        rarity, species = find_species(self.species_id)
        color = _RARITY_COLOR.get(rarity or "common", "white")
        default = Style()

        # Row layout (9 tall):
        #   0–5  sprite (6 lines)
        #   6    blank
        #   7    name / species
        #   8    lvl / placeholder
        if 0 <= y <= 5:
            if self.filled:
                # Static frame A for now; menu isn't animated.
                frames = frames_for(self.species_id, "idle")
                sprite = frames[0]
                if y < len(sprite):
                    line = sprite[y]
                    style = Style(color=color, bold=(rarity in ("epic", "legendary")))
                    return _center(line, w, style)
            else:
                # Empty slot: just show a little placeholder in the middle row.
                if y == 3:
                    return _center("?" * 5, w, Style(color="grey50"))
            return _blank(w)

        if y == 7:
            if self.filled:
                name = (self.entry or {}).get("name") or (species["name"] if species else "?")
                marker = "★ " if self.active else ""
                return _center(f"{marker}{name}", w, Style(color=color, bold=True))
            name = species["name"] if species else "?"
            return _center(name, w, Style(color="grey50"))

        if y == 8:
            if self.filled:
                lvl = _buddy_level(self.entry or {})
                return _center(f"lvl {lvl}", w, Style(color="grey70"))
            return _center("locked", w, Style(color="grey35"))

        return _blank(w)


def _blank(w: int) -> Strip:
    return Strip([Segment(" " * w, Style())])


def _center(text: str, width: int, style: Style) -> Strip:
    pad = max(0, width - len(text))
    pl = pad // 2
    pr = pad - pl
    return Strip([
        Segment(" " * pl, Style()),
        Segment(text, style),
        Segment(" " * pr, Style()),
    ])


class _Header(Static):
    """Top row: global level, tokens, shards, plus the hatch banner when
    shards are ready to redeem."""

    def __init__(self, collection: dict, **kwargs) -> None:
        super().__init__(**kwargs)
        self.collection = collection

    def on_mount(self) -> None:
        self.refresh_content()

    def refresh_content(self) -> None:
        c = self.collection
        gl = global_level(c)
        avail = hatches_available(c)
        sh = shards(c)
        n_buddies = len(all_buddies(c))

        parts = [
            f"[b]{n_buddies}[/] buddy(s)",
            f"global lvl [b]{gl}[/]",
            f"tokens [b]{avail}[/]",
            f"shards [b]{sh}[/]",
        ]
        banner = ""
        if sh >= SHARDS_PER_REDEEM:
            banner = f"  [on #883333][b white] ⚑  hatch available — press [H] or click  [/][/]"
        self.update("  ·  ".join(parts) + banner)


class GachaMenu(ModalScreen):
    """Full-roster collection menu, centered modal over the TUI."""

    DEFAULT_CSS = """
    GachaMenu {
        align: center middle;
    }
    #gacha-panel {
        width: 60%;
        height: 70%;
        min-width: 70;
        min-height: 24;
        background: $panel;
        border: round $primary;
        padding: 1 2;
        layout: vertical;
    }
    #gacha-header {
        height: 1;
        margin-bottom: 1;
    }
    #gacha-rows {
        height: 1fr;           /* take remaining vertical space inside the panel */
        overflow-y: auto;      /* scrollable, but we drive it via the cursor */
        scrollbar-size: 0 0;   /* hide scrollbar — this is a menu, not a document */
    }
    .rarity-row {
        height: auto;
        layout: horizontal;
        margin-bottom: 1;
    }
    .rarity-label {
        width: 12;
        height: 9;
        content-align: left top;
        color: grey;
    }
    _Slot {
        border: solid $panel-lighten-1;
    }
    /* Cursor highlight — bright cyan border, no tinted fill. The ★ glyph
       next to the active buddy's name still shows which is active, so
       we don't need a second border style. */
    _Slot.-selected {
        border: heavy cyan;
    }
    #gacha-footer {
        height: 1;
        color: grey;
        content-align: center middle;
    }
    """

    BINDINGS = [
        Binding("q", "close", "Close", show=True),
        Binding("escape", "close", "Close", show=False),  # alt; not advertised
        Binding("left", "move(-1,0)", "←", show=False),
        Binding("right", "move(1,0)", "→", show=False),
        Binding("up", "move(0,-1)", "↑", show=False),
        Binding("down", "move(0,1)", "↓", show=False),
        Binding("enter", "select", "Switch", show=True),
        Binding("h", "hatch", "Hatch", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._collection = _load_collection()
        # Grid is list[list[_Slot]] — outer = rarity rows, inner = slots in
        # that rarity. Cursor (ry, rx) picks a slot.
        self._rows: list[list[_Slot]] = []
        self._cursor: tuple[int, int] = (0, 0)

    def compose(self):
        panel = Container(id="gacha-panel")
        with panel:
            yield _Header(self._collection, id="gacha-header")
            # The rarity rows live inside a scrollable container so tall
            # grids (many species, or cramped terminals) can be scrolled.
            # _CursorDrivenScroll strips the default up/down/left/right
            # bindings so the modal's cursor movement takes over.
            rows = _CursorDrivenScroll(id="gacha-rows", can_focus=False)
            with rows:
                for rarity in RARITY_ORDER:
                    row = Horizontal(classes="rarity-row")
                    with row:
                        yield Static(rarity.upper(), classes="rarity-label")
                        for species in SPECIES[rarity]:
                            entry = self._find_entry(species["id"])
                            active = entry is not None and self._collection.get("active_id") == species["id"]
                            yield _Slot(
                                species["id"],
                                entry,
                                active=active,
                                id=f"slot-{species['id']}",
                            )
            yield Static("↑↓←→ navigate  ·  Enter switch  ·  H hatch  ·  q close", id="gacha-footer")

    def _find_entry(self, species_id: str) -> dict | None:
        for buddy in all_buddies(self._collection):
            if buddy.get("species_id") == species_id:
                return buddy
        return None

    def on_mount(self) -> None:
        # Collect slot rows keyed by rarity order, select the first filled
        # slot (prefer the active buddy).
        self._rows = []
        for rarity in RARITY_ORDER:
            row: list[_Slot] = []
            for species in SPECIES[rarity]:
                slot = self.query_one(f"#slot-{species['id']}", _Slot)
                if slot.active:
                    slot.add_class("-active")
                row.append(slot)
            self._rows.append(row)
        start = self._find_first_filled() or (0, 0)
        self._move_cursor(start)

    def _find_first_filled(self) -> tuple[int, int] | None:
        # Prefer the active buddy's slot.
        for ry, row in enumerate(self._rows):
            for rx, slot in enumerate(row):
                if slot.active:
                    return (ry, rx)
        for ry, row in enumerate(self._rows):
            for rx, slot in enumerate(row):
                if slot.filled:
                    return (ry, rx)
        return None

    def _move_cursor(self, pos: tuple[int, int]) -> None:
        ry, rx = pos
        ry = max(0, min(ry, len(self._rows) - 1))
        rx = max(0, min(rx, len(self._rows[ry]) - 1))
        # Clear previous selection.
        for row in self._rows:
            for slot in row:
                slot.remove_class("-selected")
        target = self._rows[ry][rx]
        target.add_class("-selected")
        self._cursor = (ry, rx)
        # Standard menu behaviour: when the cursor lands on a slot that
        # isn't fully on-screen, scroll the minimum distance to bring it
        # into view, centred. No-op when the target is already visible.
        try:
            rows = self.query_one("#gacha-rows")
            rows.scroll_to_widget(target, animate=False, center=True)
        except Exception:
            pass

    # ── actions ────────────────────────────────────────────────────────────

    def action_close(self) -> None:
        self.dismiss()

    def action_move(self, dx: int, dy: int) -> None:
        ry, rx = self._cursor

        if dx != 0:
            # Horizontal: flow across rows at the boundaries. Right past the
            # end of a row drops to the start of the next; left past the
            # start of a row jumps to the end of the previous.
            rx += dx
            if rx < 0:
                if ry > 0:
                    ry -= 1
                    rx = len(self._rows[ry]) - 1
                else:
                    rx = 0
            elif rx >= len(self._rows[ry]):
                if ry < len(self._rows) - 1:
                    ry += 1
                    rx = 0
                else:
                    rx = len(self._rows[ry]) - 1
        elif dy != 0:
            ry = max(0, min(ry + dy, len(self._rows) - 1))
            # Keep column stable; clamp if new row is shorter.
            rx = min(rx, len(self._rows[ry]) - 1)

        self._move_cursor((ry, rx))

    def action_select(self) -> None:
        ry, rx = self._cursor
        slot = self._rows[ry][rx]
        if not slot.filled:
            return  # empty slots are visual-only
        if _switch.switch_to(slot.species_id):
            # Re-read the collection, update active highlights, close.
            self.dismiss(("switched", slot.species_id))

    def action_hatch(self) -> None:
        """Step 1: push a MessageBox prompt asking 'tokens or shards?'.
        The prompt dismisses with ("choice", "t"|"s") which routes to the
        right hatch path, or ("cancelled", None) which does nothing."""
        self.app.push_screen(
            MessageBox(
                "Use tokens or shards?",
                kind="prompt",
                choices=("t", "s"),
            ),
            self._after_hatch_choice,
        )

    def _after_hatch_choice(self, result) -> None:
        if not isinstance(result, tuple) or result[0] != "choice":
            return
        key = result[1]
        if key == "t":
            self._hatch_with_tokens()
        elif key == "s":
            self._hatch_with_shards()

    def _hatch_with_tokens(self) -> None:
        # Pre-check: if no token is available (and we're not on a starter-
        # gift empty roster), show an error MessageBox instead of rolling.
        starter = len(self._collection.get("buddies", {})) == 0
        if not starter and hatches_available(self._collection) <= 0:
            self.app.push_screen(
                MessageBox("Not enough tokens (1 required to roll).", kind="error")
            )
            return
        # Push the overlay on top of this menu — the gacha menu stays in
        # the screen stack underneath. The overlay performs the roll at
        # CRACK_END and pops itself on q, landing the user back here.
        self.app.push_screen(HatchOverlay("tokens"), self._after_hatch_overlay)

    def _hatch_with_shards(self) -> None:
        if shards(self._collection) < SHARDS_PER_REDEEM:
            self.app.push_screen(
                MessageBox(
                    f"Not enough shards ({SHARDS_PER_REDEEM} required to roll).",
                    kind="error",
                )
            )
            return
        self.app.push_screen(HatchOverlay("shards"), self._after_hatch_overlay)

    def _after_hatch_overlay(self, _result) -> None:
        """Overlay closed → reload the collection and poke each slot so
        newly-filled species show their sprite. Active stays on whoever
        it was before — the user picks whether to switch via Enter on
        the new slot."""
        self._collection = _load_collection()
        active_id = self._collection.get("active_id")
        for row in self._rows:
            for slot in row:
                new_entry = self._find_entry(slot.species_id)
                slot.entry = new_entry
                slot.filled = new_entry is not None
                slot.active = slot.filled and slot.species_id == active_id
                if slot.active:
                    slot.add_class("-active")
                else:
                    slot.remove_class("-active")
                slot.refresh()
        # Header stats (tokens/shards/count) also need a repaint.
        header = self.query_one("#gacha-header", _Header)
        header.collection = self._collection
        header.refresh_content()

    async def on_click(self, event: events.Click) -> None:
        # Click on the header shard banner = open the hatch prompt.
        if event.widget is None:
            return
        widget = event.widget
        if widget.id == "gacha-header" and (
            hatches_available(self._collection) > 0
            or shards(self._collection) >= SHARDS_PER_REDEEM
        ):
            self.action_hatch()
