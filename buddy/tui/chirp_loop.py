"""Chirp state machine.

The loop ticks once per second (driven by Textual's set_interval). Each tick
calls advance() exactly once. advance() inspects the current state, performs
one transition, and returns. Never more than one state change per tick —
that's the contract that makes this thing observable and easy to reason
about.

All side-effecty collaborators (state I/O, speak roll, target pick, Claude
call) are injected as callables. That keeps this module framework-agnostic
and the unit tests cheap.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

USER_PROMPT_MAX = 300
ASSISTANT_RESPONSE_MAX = 200


class ChirpState(Enum):
    IDLE = "idle"
    WILL_SPEAK = "will_speak"
    DRAFTING = "drafting"
    READY = "ready"
    SPOKEN = "spoken"


ReadState = Callable[[], dict]
WriteState = Callable[[dict], None]
RollSpeak = Callable[[str], bool]                        # (event_kind) -> bool
PickTarget = Callable[[list[str]], str]                  # (options) -> choice
KickDraft = Callable[[str, str], None]                   # (target, text) -> None
PollDraft = Callable[[], tuple[bool, Optional[str]]]     # -> (done, chirp_or_none)


@dataclass
class ChirpLoop:
    """One-step-at-a-time chirp state machine."""

    read_state: ReadState
    write_state: WriteState
    roll_speak: RollSpeak
    pick_target: PickTarget
    kick_draft: KickDraft
    poll_draft: PollDraft
    ttl_seconds: float = 12.0

    state: ChirpState = ChirpState.IDLE
    _current_event: Optional[dict] = None
    _current_target: Optional[str] = None
    _drafted_chirp: Optional[str] = None
    _chirp_end_ts: float = 0.0

    def advance(self) -> None:
        """Perform exactly one state transition."""
        if self.state is ChirpState.IDLE:
            self._from_idle()
        elif self.state is ChirpState.WILL_SPEAK:
            self._from_will_speak()
        elif self.state is ChirpState.DRAFTING:
            self._from_drafting()
        elif self.state is ChirpState.READY:
            self._from_ready()
        elif self.state is ChirpState.SPOKEN:
            self._from_spoken()

    # ── transitions ─────────────────────────────────────────────────────

    def _from_idle(self) -> None:
        s = self.read_state()
        queue = s.get("pending_events") or []
        if not queue:
            return
        event = queue[0]
        # Pop the event regardless of whether we chirp on it.
        remaining = queue[1:]
        new_state = dict(s)
        new_state["pending_events"] = remaining
        self.write_state(new_state)

        if not self.roll_speak(event.get("kind", "stop")):
            # Roll said no — stay IDLE, event dropped.
            return

        self._current_event = event
        self.state = ChirpState.WILL_SPEAK

    def _from_will_speak(self) -> None:
        event = self._current_event or {}
        options: list[str] = []
        if (event.get("user_prompt") or "").strip():
            options.append("user_prompt")
        if (event.get("assistant_response") or "").strip():
            options.append("assistant_response")

        if not options:
            # Nothing to react to — back to idle.
            self._reset_event()
            self.state = ChirpState.IDLE
            return

        target = self.pick_target(options)
        if target not in options:
            target = options[0]

        raw = event.get(target, "") or ""
        text = _truncate_for(target, raw)

        self._current_target = target
        self.kick_draft(target, text)
        self.state = ChirpState.DRAFTING

    def _from_drafting(self) -> None:
        done, chirp = self.poll_draft()
        if not done:
            return  # stay in DRAFTING
        self._drafted_chirp = chirp
        self.state = ChirpState.READY

    def _from_ready(self) -> None:
        chirp = self._drafted_chirp
        if not chirp:
            # Claude call failed — nothing to show.
            self._reset_event()
            self.state = ChirpState.IDLE
            return

        now = time.time()
        s = dict(self.read_state())
        s["speech"] = chirp
        s["speech_ts"] = now
        s["last_speech_ts"] = now
        self.write_state(s)
        self._chirp_end_ts = now + self.ttl_seconds
        self.state = ChirpState.SPOKEN

    def _from_spoken(self) -> None:
        if time.time() >= self._chirp_end_ts:
            self._reset_event()
            self.state = ChirpState.IDLE

    # ── helpers ─────────────────────────────────────────────────────────

    def _reset_event(self) -> None:
        self._current_event = None
        self._current_target = None
        self._drafted_chirp = None
        self._chirp_end_ts = 0.0


def _truncate_for(target: str, text: str) -> str:
    """Cap context before it hits Claude. Policy lives in the loop, not speak.py."""
    text = text or ""
    if target == "user_prompt":
        return text[:USER_PROMPT_MAX]
    if target == "assistant_response":
        if len(text) > ASSISTANT_RESPONSE_MAX:
            return text[-ASSISTANT_RESPONSE_MAX:]
        return text
    return text[:USER_PROMPT_MAX]
