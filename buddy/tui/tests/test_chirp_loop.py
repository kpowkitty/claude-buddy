"""Tests for the chirp state machine.

ChirpLoop is a pure state machine. Each call to advance() performs exactly
one transition. Randomness (speak roll, target pick) and the slow Claude
call are injected as callables, so tests drive the loop deterministically.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import pytest

from chirp_loop import ChirpLoop, ChirpState


# ───────────────────────── fakes ─────────────────────────


@dataclass
class FakeState:
    """Stand-in for the state.json read/write path."""
    data: dict = field(default_factory=dict)

    def read(self) -> dict:
        return dict(self.data)

    def write(self, new: dict) -> None:
        self.data = dict(new)


class FakeDrafter:
    """Emulates the async Claude call with explicit control.

    Tests call .complete(chirp_or_none) to simulate the draft finishing.
    """

    def __init__(self) -> None:
        self.called_with: list[tuple[str, str]] = []
        self._next_result: str | None = None
        self._completed: bool = False

    def __call__(self, target: str, text: str) -> None:
        # In production this kicks off an async task; here we just record.
        self.called_with.append((target, text))

    def poll(self) -> tuple[bool, str | None]:
        """Returns (done, chirp). Loop calls this each tick while DRAFTING."""
        if not self._completed:
            return (False, None)
        return (True, self._next_result)

    def complete(self, chirp: str | None) -> None:
        self._next_result = chirp
        self._completed = True

    def reset(self) -> None:
        self._completed = False
        self._next_result = None


def _make_loop(
    state: FakeState | None = None,
    roll: bool = True,
    target: str = "user_prompt",
    drafter: FakeDrafter | None = None,
    ttl: float = 12.0,
) -> tuple[ChirpLoop, FakeState, FakeDrafter]:
    state = state or FakeState()
    drafter = drafter or FakeDrafter()
    loop = ChirpLoop(
        read_state=state.read,
        write_state=state.write,
        roll_speak=lambda event: roll,
        pick_target=lambda opts: target if target in opts else opts[0],
        kick_draft=drafter,
        poll_draft=drafter.poll,
        ttl_seconds=ttl,
    )
    return loop, state, drafter


# ───────────────────────── invariants ─────────────────────────


def test_starts_in_idle() -> None:
    loop, _, _ = _make_loop()
    assert loop.state is ChirpState.IDLE


def test_idle_with_no_event_stays_idle() -> None:
    loop, _, _ = _make_loop()
    loop.advance()
    assert loop.state is ChirpState.IDLE


# ───────────────────────── event → no speak (roll=False) ─────────────────────────


def test_event_with_roll_false_drops_event_and_stays_idle() -> None:
    state = FakeState(data={
        "pending_events": [{"kind": "stop", "user_prompt": "hi", "assistant_response": "hello"}]
    })
    loop, _, _ = _make_loop(state=state, roll=False)
    loop.advance()
    assert loop.state is ChirpState.IDLE
    assert state.data.get("pending_events") == []


# ───────────────────────── happy path ─────────────────────────


def test_happy_path_full_cycle() -> None:
    state = FakeState(data={
        "pending_events": [{"kind": "stop", "user_prompt": "refactor reflow", "assistant_response": "done"}]
    })
    loop, state, drafter = _make_loop(state=state, roll=True, target="user_prompt")

    # Tick 1: IDLE → WILL_SPEAK (pulled event off queue)
    loop.advance()
    assert loop.state is ChirpState.WILL_SPEAK
    assert state.data.get("pending_events") == []

    # Tick 2: WILL_SPEAK → DRAFTING (picked target, kicked draft)
    loop.advance()
    assert loop.state is ChirpState.DRAFTING
    assert drafter.called_with == [("user_prompt", "refactor reflow")]

    # Tick 3: DRAFTING → DRAFTING (still in flight)
    loop.advance()
    assert loop.state is ChirpState.DRAFTING

    # Draft completes with a chirp
    drafter.complete("rrr. my reflow.")

    # Tick 4: DRAFTING → READY
    loop.advance()
    assert loop.state is ChirpState.READY

    # Tick 5: READY → SPOKEN (wrote chirp to state)
    loop.advance()
    assert loop.state is ChirpState.SPOKEN
    assert state.data["speech"] == "rrr. my reflow."
    assert state.data["speech_ts"] > 0
    assert state.data["last_speech_ts"] > 0


# ───────────────────────── target selection ─────────────────────────


def test_target_is_user_prompt_when_only_prompt_present() -> None:
    state = FakeState(data={
        "pending_events": [{"kind": "stop", "user_prompt": "hi", "assistant_response": ""}]
    })
    loop, _, drafter = _make_loop(state=state, target="assistant_response")
    loop.advance()  # → WILL_SPEAK
    loop.advance()  # → DRAFTING (must pick user_prompt since response empty)
    assert drafter.called_with[0][0] == "user_prompt"


def test_target_is_assistant_response_when_only_response_present() -> None:
    state = FakeState(data={
        "pending_events": [{"kind": "stop", "user_prompt": "", "assistant_response": "ok done"}]
    })
    loop, _, drafter = _make_loop(state=state, target="user_prompt")
    loop.advance()
    loop.advance()
    assert drafter.called_with[0][0] == "assistant_response"


def test_target_truncates_long_user_prompt() -> None:
    long = "x" * 400
    state = FakeState(data={"pending_events": [{"kind": "stop", "user_prompt": long, "assistant_response": ""}]})
    loop, _, drafter = _make_loop(state=state)
    loop.advance()
    loop.advance()
    _, text = drafter.called_with[0]
    assert len(text) == 300


def test_target_truncates_long_assistant_response_to_last_200() -> None:
    long = "a" * 400 + "END"
    state = FakeState(data={"pending_events": [{"kind": "stop", "user_prompt": "", "assistant_response": long}]})
    loop, _, drafter = _make_loop(state=state)
    loop.advance()
    loop.advance()
    _, text = drafter.called_with[0]
    assert len(text) == 200
    # Last 200 chars — so "END" must be at the end
    assert text.endswith("END")


# ───────────────────────── failure paths ─────────────────────────


def test_draft_returns_none_goes_straight_back_to_idle() -> None:
    state = FakeState(data={"pending_events": [{"kind": "stop", "user_prompt": "hi", "assistant_response": ""}]})
    loop, state, drafter = _make_loop(state=state)
    loop.advance()  # WILL_SPEAK
    loop.advance()  # DRAFTING
    drafter.complete(None)
    loop.advance()  # DRAFTING → READY (chirp is None)
    assert loop.state is ChirpState.READY
    loop.advance()  # READY → IDLE (nothing to display)
    assert loop.state is ChirpState.IDLE
    assert "speech" not in state.data


# ───────────────────────── TTL expiration ─────────────────────────


def test_spoken_transitions_to_idle_after_ttl() -> None:
    state = FakeState(data={"pending_events": [{"kind": "stop", "user_prompt": "hi", "assistant_response": ""}]})
    loop, state, drafter = _make_loop(state=state, ttl=0.05)
    loop.advance()  # WILL_SPEAK
    loop.advance()  # DRAFTING
    drafter.complete("yo")
    loop.advance()  # READY
    loop.advance()  # SPOKEN
    assert loop.state is ChirpState.SPOKEN
    time.sleep(0.1)
    loop.advance()
    assert loop.state is ChirpState.IDLE


def test_spoken_stays_until_ttl_expires() -> None:
    state = FakeState(data={"pending_events": [{"kind": "stop", "user_prompt": "hi", "assistant_response": ""}]})
    loop, state, drafter = _make_loop(state=state, ttl=10.0)
    loop.advance()
    loop.advance()
    drafter.complete("yo")
    loop.advance()
    loop.advance()
    assert loop.state is ChirpState.SPOKEN
    loop.advance()
    loop.advance()
    assert loop.state is ChirpState.SPOKEN  # still within TTL


# ───────────────────────── multi-event queue behavior ─────────────────────────


def test_second_event_waits_until_loop_returns_to_idle() -> None:
    state = FakeState(data={
        "pending_events": [
            {"kind": "stop", "user_prompt": "a", "assistant_response": ""},
            {"kind": "stop", "user_prompt": "b", "assistant_response": ""},
        ]
    })
    loop, state, drafter = _make_loop(state=state, ttl=0.01)
    # First cycle consumes one event.
    loop.advance()  # IDLE → WILL_SPEAK (pops event 'a')
    assert len(state.data["pending_events"]) == 1
    loop.advance()  # DRAFTING
    drafter.complete("x")
    loop.advance()  # READY
    loop.advance()  # SPOKEN
    time.sleep(0.02)
    loop.advance()  # SPOKEN → IDLE
    # Second cycle should pick up event 'b'.
    drafter.reset()
    loop.advance()  # IDLE → WILL_SPEAK (pops 'b')
    assert loop.state is ChirpState.WILL_SPEAK
    assert state.data["pending_events"] == []
    loop.advance()
    assert drafter.called_with[-1][1] == "b"
