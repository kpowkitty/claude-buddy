"""BuddyApp — the Textual application.

Composes PtyTerminal (embedded Claude) on the left and Habitat on the right.
Routes key events to the pty, with a few app-level hotkeys reserved for
quit / toggle / pet.
"""
from __future__ import annotations

import os
import pathlib
import sys
import threading
import time
from typing import Sequence

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Static

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUDDY = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _BUDDY)

from chirp_loop_wiring import build_chirp_loop  # noqa: E402
from collection import active_buddy, migrate  # noqa: E402
from gacha_menu import GachaMenu  # noqa: E402
from habitat import Habitat, HABITAT_WIDTH  # noqa: E402
from input_map import key_to_bytes  # noqa: E402
from personality import for_species  # noqa: E402
from pty_terminal import PtyTerminal  # noqa: E402
import speak  # noqa: E402
from state import BUDDY_DIR, IS_TEST_MODE, PROGRESSION, STATE, read_json, update_state, write_atomic  # noqa: E402


def _read_active_prog() -> dict | None:
    raw = read_json(PROGRESSION, None)
    if raw is None:
        return None
    return active_buddy(migrate(raw))

_BUDDY_DIR = pathlib.Path(BUDDY_DIR)


class BuddyApp(App):
    # Textual reserves Ctrl+P for its command palette; we want Ctrl+P for
    # petting the buddy, so turn the palette off.
    ENABLE_COMMAND_PALETTE = False

    CSS = f"""
    Screen {{
        /* Three layers:
             base    — Claude's pty fills everything.
             overlay — Habitat (floating pet) sits in the top-right.
             topmost — TEST MODE banner so it never fights the habitat.
           The L-reflow in pty_terminal reserves the top-right rectangle
           so Claude's text never lands under the habitat. */
        layers: base overlay topmost;
        background: rgba(0, 0, 0, 0);
    }}
    PtyTerminal {{
        layer: base;
        width: 100%;
        height: 100%;
    }}
    Habitat {{
        layer: overlay;
        dock: right;
        width: {HABITAT_WIDTH};
        height: auto;
    }}
    Footer {{
        dock: bottom;
        background: rgba(0, 0, 0, 0);
    }}
    #test-mode-banner {{
        dock: top;
        layer: topmost;
        height: 1;
        background: red;
        color: white;
        text-style: bold;
        content-align: center middle;
    }}
    """

    # Function keys are the safe pick for app hotkeys — Claude Code
    # (and readline-style consoles generally) never bind them, so our
    # keys never fight Claude's input muscle memory.
    # Ctrl+Q stays because quitting an embedded-terminal TUI is a
    # near-universal convention; users expect the whole app to close,
    # not the inner shell's own Ctrl+Q.
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("f1", "pet", "Pet", show=True),
        Binding("f2", "gacha", "Gacha", show=True),
        Binding("f3", "toggle_skills", "Skills", show=True),
        Binding("f4", "toggle_habitat", "Toggle buddy", show=True),
        Binding("f5", "refresh_view", "Refresh", show=True),
        # Display-only hint for the terminal-native selection gesture.
        # The action is a no-op; Textual never routes shift-drag here
        # (the outer terminal captures it first, which is the point).
        Binding("shift+drag", "noop", "Select", show=True, key_display="shift+drag"),
    ]

    def action_noop(self) -> None:
        pass

    def __init__(self, command: Sequence[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self._command = list(command)
        self._habitat_visible = True
        self._chirp_loop = build_chirp_loop()
        # Running record of what the user has typed on the current line.
        # Not a mirror of Claude's input box — just our view of the user's
        # keystrokes since the last Enter. Used to detect "~{buddy}" prefix.
        self._typed_line: str = ""

    def compose(self) -> ComposeResult:
        if IS_TEST_MODE:
            # Loud red bar pinned to the top so you never forget you're
            # operating on a throwaway progression file.
            yield Static(
                f" ⚠  TEST MODE  ·  state dir: {BUDDY_DIR}  ⚠ ",
                id="test-mode-banner",
            )
        with Horizontal():
            yield PtyTerminal(self._command, id="pty")
            yield Habitat(id="habitat")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#pty", PtyTerminal).focus()
        # Tick the chirp state machine once per second.
        self.set_interval(1.0, self._chirp_loop.advance)

    # ── actions ────────────────────────────────────────────────────────────

    def action_toggle_habitat(self) -> None:
        habitat = self.query_one("#habitat", Habitat)
        self._habitat_visible = not self._habitat_visible
        habitat.display = self._habitat_visible
        # Tell the PTY about the habitat state change: it gates the
        # L-shape reflow and decides whether Claude gets narrow or
        # full-width COLUMNS. set_habitat_visible triggers the resize
        # + Ctrl+L repaint internally.
        pty = self.query_one("#pty", PtyTerminal)
        self.call_after_refresh(pty.set_habitat_visible, self._habitat_visible)

    def action_toggle_skills(self) -> None:
        self.query_one("#habitat", Habitat).toggle_skills()

    def action_gacha(self) -> None:
        """Open the gacha collection menu (full roster, rarity-grouped)."""
        self.push_screen(GachaMenu())

    def action_refresh_view(self) -> None:
        """Force a redraw when the view gets corrupted (usually after a
        resize). Wipes pyte's screen, re-syncs the pty size, and asks
        Claude to repaint via Ctrl+L."""
        pty = self.query_one("#pty", PtyTerminal)
        if pty._screen is not None:
            pty._screen.reset()
        # Re-propagate the current widget size so pyte & the child agree.
        cols = max(20, pty.size.width)
        rows = max(5, pty.size.height)
        pty.resize_to(cols, rows)
        # Ctrl+L tells Claude Code to redraw its UI from scratch.
        pty.write_bytes(b"\x0c")
        pty.refresh()

    # How long the "petted" mood + prrr speech persists. Bump this if the
    # purr feels too brief, or wire it to a personality trait later.
    PET_REACTION_SECONDS = 2.0

    def action_pet(self) -> None:
        """Pet the active buddy.

        Three visible effects:
          1. pets_received counter ticks up on the buddy.
          2. `petted_until` in state.json makes derive_mood return 'petted'
             for PET_REACTION_SECONDS (closes eyes + smiles via sprite swap).
          3. Speech bubble says "prrr" for the same window.
        """
        raw = read_json(PROGRESSION, None)
        if raw is None:
            return
        collection = migrate(raw)
        active_id = collection.get("active_id")
        buddy = active_buddy(collection)
        if not active_id or buddy is None:
            return

        buddy = dict(buddy)
        buddy["pets_received"] = int(buddy.get("pets_received", 0)) + 1
        collection["buddies"] = dict(collection.get("buddies", {}))
        collection["buddies"][active_id] = buddy
        write_atomic(PROGRESSION, collection)

        now = time.time()
        state = read_json(STATE, {}) or {}
        state["petted_until"] = now + self.PET_REACTION_SECONDS
        state["speech"] = "prrr"
        state["speech_ts"] = now
        state["last_speech_ts"] = now
        write_atomic(STATE, state)

    # ── input routing ──────────────────────────────────────────────────────

    async def on_key(self, event) -> None:
        # If a modal (e.g. the gacha menu) is on top of the screen stack,
        # the modal owns the keyboard. We must not forward anything to
        # the pty — otherwise Claude sees the user's menu navigation.
        from textual.screen import ModalScreen
        if isinstance(self.screen, ModalScreen):
            return

        # Shift+PageUp/Down page the local scrollback. Shift+End returns
        # to the live tail. Plain PageUp/Down/End still pass through so
        # Claude keeps its own navigation.
        if event.key in ("shift+pageup", "shift+pagedown"):
            pty = self.query_one("#pty", PtyTerminal)
            pty.scroll_history(-1 if event.key == "shift+pageup" else +1)
            event.stop()
            return
        if event.key == "shift+end":
            pty = self.query_one("#pty", PtyTerminal)
            pty.resume_live()
            event.stop()
            return

        pty = self.query_one("#pty", PtyTerminal)

        # Enter: peek at what the user just typed. If it starts with the
        # buddy-talk prefix, wipe Claude's input line and fire a buddy
        # reply instead of forwarding Enter.
        if event.key in ("enter", "return"):
            line = self._typed_line
            self._typed_line = ""
            if self._is_buddy_message(line):
                message = line[1 + len(self._buddy_name()):].strip()
                # Ctrl+U clears the line in Claude's input editor. Send
                # that instead of Enter — Claude never processes the msg.
                pty.write_bytes(b"\x15")
                if message:
                    # Any direct message from the user counts as interaction —
                    # wake the buddy so it can respond, then fire the reply.
                    self._wake_buddy()
                    self._fire_buddy_reply(message)
                event.stop()
                return
            # Not a buddy message — forward Enter to Claude as usual. A
            # prompt to Claude also counts as activity; bump last_event_ts
            # so a sleeping buddy wakes up.
            self._wake_buddy()
            pty.write_bytes(b"\r")
            event.stop()
            return

        # Don't forward our own app-level hotkeys to the pty — otherwise
        # Claude sees the raw control byte too (e.g. Ctrl+P lands as \x10
        # and triggers Claude's previous-prompt history).
        if event.key in {b.key for b in self.BINDINGS}:
            return

        data = key_to_bytes(event)
        if data is None:
            return
        self._update_typed_line(event)
        pty.write_bytes(data)
        event.stop()

    async def on_paste(self, event) -> None:
        """Forward pasted text to the child as a bracketed paste.

        Textual emits Paste events separately from Key events, so they never
        reach on_key — without this handler, pastes silently vanish. Wrapping
        in \\x1b[200~ ... \\x1b[201~ lets Claude tell pasted content apart from
        typed content (prevents a multi-line paste being processed as a bunch
        of Enter presses).
        """
        # Modal on top owns input — don't bleed paste bytes to the pty.
        from textual.screen import ModalScreen
        if isinstance(self.screen, ModalScreen):
            return
        text = event.text
        if not text:
            return
        pty = self.query_one("#pty", PtyTerminal)
        # Keep our typed-line buffer in sync so a paste that starts with
        # `~{name}` still routes correctly on a subsequent Enter.
        self._typed_line += text
        pty.write_bytes(b"\x1b[200~" + text.encode("utf-8", errors="replace") + b"\x1b[201~")
        event.stop()

    # ── buddy talk intercept ──────────────────────────────────────────────

    def _update_typed_line(self, event) -> None:
        """Keep a running record of what the user typed on the current line.

        Printable chars append; backspace pops one; Ctrl+U/Ctrl+C clear.
        Arrow keys / history navigation aren't tracked precisely — a misfire
        just means the message goes to Claude normally, which is safe.
        """
        key = event.key
        if key == "backspace":
            self._typed_line = self._typed_line[:-1]
            return
        if key in ("ctrl+u", "ctrl+c"):
            self._typed_line = ""
            return
        ch = getattr(event, "character", None)
        if ch and ch.isprintable():
            self._typed_line += ch

    def _buddy_name(self) -> str:
        prog = _read_active_prog() or {}
        return (prog.get("name") or prog.get("species_name") or "").strip()

    def _is_buddy_message(self, line: str) -> bool:
        name = self._buddy_name()
        if not name:
            return False
        if not line.startswith("~"):
            return False
        rest = line[1:]
        return rest[: len(name)].lower() == name.lower()

    def _wake_buddy(self) -> None:
        """Stamp last_event_ts so derive_mood flips out of 'sleeping'.

        Called when the user prompts Claude or talks to the buddy directly.
        Keeps the buddy feeling responsive — if you've been afk for ages
        and then actually interact, the buddy wakes up instead of snoring
        through the conversation.
        """
        try:
            update_state(last_event="user_input")
        except Exception:
            # State updates are best-effort; a failure here shouldn't
            # block the keystroke from reaching Claude.
            pass

    def _fire_buddy_reply(self, message: str) -> None:
        """Fire-and-forget: ask Claude (as the buddy) to reply. Writes the
        result to state.json's speech field so the existing bubble surfaces it."""
        prog = _read_active_prog() or {}
        species_id = prog.get("species_id")
        if not species_id:
            return
        pers = for_species(species_id)
        system = speak.build_system(prog, pers)
        user = speak.build_user("the user's direct message to you", message)

        def _work() -> None:
            try:
                reply = speak.call_claude(system, user)
            except Exception:
                reply = None
            if not reply:
                return
            now = time.time()
            state = read_json(STATE, {}) or {}
            state["speech"] = reply
            state["speech_ts"] = now
            state["last_speech_ts"] = now
            write_atomic(STATE, state)

        threading.Thread(target=_work, daemon=True).start()
