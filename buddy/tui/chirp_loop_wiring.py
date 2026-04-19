"""Production wiring for ChirpLoop.

Builds a ChirpLoop with real collaborators (state.json I/O, speak.py,
random). Separated from chirp_loop.py so that module stays pure + testable.
"""
from __future__ import annotations

import os
import random
import sys
import threading
from typing import Optional

from chirp_loop import ChirpLoop

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUDDY = os.path.dirname(_HERE)
sys.path.insert(0, _BUDDY)

from state import STATE, read_json, write_atomic  # noqa: E402
import state as _state_mod  # noqa: E402
from collection import active_buddy, migrate  # noqa: E402
from personality import for_species  # noqa: E402
import speak  # noqa: E402


def _read_active_prog() -> dict | None:
    raw = read_json(_state_mod.PROGRESSION, None)
    if raw is None:
        return None
    return active_buddy(migrate(raw))


class _DraftSlot:
    """Thread-safe slot for a background Claude call's result.

    poll() returns (done, result). When a draft is kicked off, another
    draft can't be kicked until the loop transitions back out of DRAFTING
    (which happens after poll() reports done) — so a single slot suffices.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._done = False
        self._chirp: Optional[str] = None

    def kick(self, system: str, user: str) -> None:
        with self._lock:
            self._done = False
            self._chirp = None

        def _work() -> None:
            chirp: Optional[str]
            try:
                chirp = speak.call_claude(system, user)
            except Exception:
                chirp = None
            with self._lock:
                self._chirp = chirp
                self._done = True

        threading.Thread(target=_work, daemon=True).start()

    def poll(self) -> tuple[bool, Optional[str]]:
        with self._lock:
            return (self._done, self._chirp)


def build_chirp_loop() -> ChirpLoop:
    slot = _DraftSlot()

    def _read() -> dict:
        return read_json(STATE, {})

    def _write(new: dict) -> None:
        write_atomic(STATE, new)

    def _roll(event_kind: str) -> bool:
        prog = _read_active_prog()
        if not prog:
            return False
        state = read_json(STATE, {})
        return speak.should_speak(prog, state, event_kind)

    def _pick(options: list[str]) -> str:
        return random.choice(options) if options else ""

    def _kick(target: str, text: str) -> None:
        prog = _read_active_prog() or {}
        pers = for_species(prog.get("species_id", ""))
        system = speak.build_system(prog, pers)
        kind = {
            "user_prompt": "a user prompt",
            "assistant_response": "a claude response",
        }.get(target, f"a {target} event")
        user = speak.build_user(kind, text)
        slot.kick(system, user)

    return ChirpLoop(
        read_state=_read,
        write_state=_write,
        roll_speak=_roll,
        pick_target=_pick,
        kick_draft=_kick,
        poll_draft=slot.poll,
    )
