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
from textual.widgets import Footer

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUDDY = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _BUDDY)

from chirp_loop_wiring import build_chirp_loop  # noqa: E402
from habitat import Habitat, HABITAT_WIDTH  # noqa: E402
from input_map import key_to_bytes  # noqa: E402
from personality import for_species  # noqa: E402
from pty_terminal import PtyTerminal  # noqa: E402
import speak  # noqa: E402
from state import BUDDY_DIR, PROGRESSION, STATE, read_json, write_atomic  # noqa: E402

_BUDDY_DIR = pathlib.Path(BUDDY_DIR)


class BuddyApp(App):
    CSS = f"""
    Screen {{
        layout: horizontal;
        background: rgba(0, 0, 0, 0);
    }}
    PtyTerminal {{
        width: 1fr;
        height: 100%;
    }}
    Habitat {{
        width: {HABITAT_WIDTH};
    }}
    Footer {{
        dock: bottom;
        background: rgba(0, 0, 0, 0);
    }}
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+b", "toggle_habitat", "Toggle buddy", show=True),
        Binding("ctrl+s", "toggle_skills", "Skills", show=True),
        Binding("ctrl+p", "pet", "Pet", show=True),
    ]

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
        # Tell the pty its size changed so Claude reflows.
        pty = self.query_one("#pty", PtyTerminal)
        self.call_after_refresh(pty.on_resize)

    def action_toggle_skills(self) -> None:
        self.query_one("#habitat", Habitat).toggle_skills()

    def action_pet(self) -> None:
        # Bump the pet counter. Chirping on pet re-lands in v2 alongside
        # other user-triggered events flowing through the chirp_loop.
        prog = read_json(PROGRESSION, {})
        if not prog.get("species_id"):
            return
        prog["pets_received"] = int(prog.get("pets_received", 0)) + 1
        write_atomic(PROGRESSION, prog)

    # ── input routing ──────────────────────────────────────────────────────

    async def on_key(self, event) -> None:
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
                    self._fire_buddy_reply(message)
                event.stop()
                return
            # Not a buddy message — forward Enter to Claude as usual.
            pty.write_bytes(b"\r")
            event.stop()
            return

        data = key_to_bytes(event)
        if data is None:
            return
        self._update_typed_line(event)
        pty.write_bytes(data)
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
        prog = read_json(PROGRESSION, {}) or {}
        return (prog.get("name") or prog.get("species_name") or "").strip()

    def _is_buddy_message(self, line: str) -> bool:
        name = self._buddy_name()
        if not name:
            return False
        if not line.startswith("~"):
            return False
        rest = line[1:]
        return rest[: len(name)].lower() == name.lower()

    def _fire_buddy_reply(self, message: str) -> None:
        """Fire-and-forget: ask Claude (as the buddy) to reply. Writes the
        result to state.json's speech field so the existing bubble surfaces it."""
        prog = read_json(PROGRESSION, {}) or {}
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
