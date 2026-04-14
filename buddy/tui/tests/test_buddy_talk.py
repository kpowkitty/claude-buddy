"""Tests for the '~{name} ...' talk-to-buddy intercept.

When the user's typed line starts with `~{buddy_name}` and they press Enter,
the line is sent to the buddy (via speak.call_claude) instead of to Claude.
Claude's input box is cleared with Ctrl+U so it never processes the line.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

from app import BuddyApp
from pty_terminal import PtyTerminal

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUDDY = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _BUDDY not in sys.path:
    sys.path.insert(0, _BUDDY)

import speak  # noqa: E402


# ─── pure prompt building ────────────────────────────────────────────────────


def test_build_user_includes_kind_and_text() -> None:
    user = speak.build_user("the user's question", "what color is the sky")
    assert "the user's question" in user
    assert "what color is the sky" in user


def test_build_user_strips_whitespace() -> None:
    user = speak.build_user("a user prompt", "  padded  ")
    assert "  padded  " not in user
    assert "padded" in user


def test_build_user_handles_empty_text() -> None:
    user = speak.build_user("a session_start event", "")
    assert user  # non-empty prompt
    assert "session_start" in user


# ─── intercept predicate ─────────────────────────────────────────────────────


def _app_with_buddy_name(name: str) -> BuddyApp:
    app = BuddyApp(["/bin/cat"])
    # Monkey-patch the name lookup — avoids touching the real state.json.
    app._buddy_name = lambda: name  # type: ignore[assignment]
    return app


def test_is_buddy_message_matches_exact_name() -> None:
    app = _app_with_buddy_name("quine")
    assert app._is_buddy_message("~quine hello") is True


def test_is_buddy_message_is_case_insensitive() -> None:
    app = _app_with_buddy_name("quine")
    assert app._is_buddy_message("~Quine") is True
    assert app._is_buddy_message("~QUINE hi") is True


def test_is_buddy_message_requires_leading_tilde() -> None:
    app = _app_with_buddy_name("quine")
    assert app._is_buddy_message("quine hi") is False
    assert app._is_buddy_message("hey ~quine") is False


def test_is_buddy_message_rejects_wrong_name() -> None:
    app = _app_with_buddy_name("quine")
    assert app._is_buddy_message("~pebble hi") is False


def test_is_buddy_message_empty_name_never_matches() -> None:
    app = _app_with_buddy_name("")
    assert app._is_buddy_message("~hi") is False


# ─── live pilot: Enter routing ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enter_with_tilde_prefix_sends_ctrl_u_not_enter() -> None:
    """The happy path: user typed `~quine hi`, hits Enter. Claude should
    receive Ctrl+U (line clear) — not `\\r` — and we should kick a reply."""
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        app._buddy_name = lambda: "quine"  # type: ignore[assignment]
        pty = app.query_one("#pty", PtyTerminal)
        writes: list[bytes] = []
        pty.write_bytes = lambda data: writes.append(data)  # type: ignore[assignment]

        fired: list[str] = []
        app._fire_buddy_reply = lambda msg: fired.append(msg)  # type: ignore[assignment]

        # Simulate the user typing `~quine hi` and pressing Enter.
        for ch in "~quine hi":
            await pilot.press(ch if ch != " " else "space")
        await pilot.press("enter")
        await pilot.pause(0.05)

        assert b"\x15" in writes, f"expected Ctrl+U in writes, got {writes!r}"
        assert b"\r" not in writes, f"Enter should not have been forwarded: {writes!r}"
        assert fired == ["hi"], f"expected buddy to be asked to reply: {fired!r}"

        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_enter_without_tilde_forwards_cr_to_claude() -> None:
    """Non-buddy input still hits Enter → Claude as usual."""
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        app._buddy_name = lambda: "quine"  # type: ignore[assignment]
        pty = app.query_one("#pty", PtyTerminal)
        writes: list[bytes] = []
        pty.write_bytes = lambda data: writes.append(data)  # type: ignore[assignment]

        fired: list[str] = []
        app._fire_buddy_reply = lambda msg: fired.append(msg)  # type: ignore[assignment]

        for ch in "hello":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause(0.05)

        assert b"\r" in writes, f"Enter should have been forwarded: {writes!r}"
        assert b"\x15" not in writes, f"no Ctrl+U for normal input: {writes!r}"
        assert fired == []

        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_backspace_removes_tilde_so_intercept_doesnt_fire() -> None:
    """If the user types `~` then backspaces before typing the name, the
    line no longer starts with ~ and Enter should flow normally."""
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        app._buddy_name = lambda: "quine"  # type: ignore[assignment]
        pty = app.query_one("#pty", PtyTerminal)
        writes: list[bytes] = []
        pty.write_bytes = lambda data: writes.append(data)  # type: ignore[assignment]

        fired: list[str] = []
        app._fire_buddy_reply = lambda msg: fired.append(msg)  # type: ignore[assignment]

        await pilot.press("~")
        await pilot.press("backspace")
        for ch in "hi":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause(0.05)

        assert b"\r" in writes
        assert fired == []

        await pilot.press("ctrl+q")
        await pilot.pause(0.1)
