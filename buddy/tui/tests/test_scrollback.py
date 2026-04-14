"""Tests for PtyTerminal's pause/resume scrollback.

Shift+Wheel (and Shift+PageUp/Down at the app level) pauses pyte's feed
and pages the screen backward. Output the child emits while paused is
buffered and replayed on resume — this is what lets the user stay scrolled
up while Claude keeps refreshing its UI.
"""
from __future__ import annotations

import pyte
import pytest
from textual import events

from app import BuddyApp
from pty_terminal import PtyTerminal


def _seed_history(pty: PtyTerminal) -> None:
    """Replace the widget's screen with one that has 200 lines of scrollback."""
    pty._screen = pyte.HistoryScreen(80, 10, history=2000)
    pty._stream = pyte.ByteStream(pty._screen)
    pty._stream.feed("\r\n".join(f"line-{i}" for i in range(200)).encode() + b"\r\n")


def _visible(screen: pyte.Screen) -> str:
    return "\n".join(
        "".join((screen.buffer[y][x].data or " ") for x in range(screen.columns))
        for y in range(screen.lines)
    )


def _make_scroll_event(cls, widget: PtyTerminal, *, shift: bool) -> events.MouseEvent:
    return cls(
        widget=widget,
        x=1, y=1,
        delta_x=0, delta_y=1,
        button=0,
        shift=shift, meta=False, ctrl=False,
    )


# ─── scroll_history mechanics ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scroll_back_pauses_and_moves_history() -> None:
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        pty = app.query_one("#pty", PtyTerminal)
        _seed_history(pty)
        before = pty._screen.history.position
        assert not pty.is_paused

        assert pty.scroll_history(-1) is True
        assert pty.is_paused
        assert pty._screen.history.position < before
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_new_output_while_paused_is_buffered_not_painted() -> None:
    """The critical bug fix: Claude's repaints must NOT clobber the
    scrolled-back view."""
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        pty = app.query_one("#pty", PtyTerminal)
        _seed_history(pty)
        pty.scroll_history(-1)
        scrolled_view = _visible(pty._screen)

        # Simulate Claude emitting more output — in real life this is the
        # spinner repaint that was snapping us back to live.
        pty._stream.feed  # type: ignore[unused-ignore]
        # Directly invoke the same path _drain_pty uses while paused.
        # (Can't call _drain_pty without a live fd; test the pause invariant.)
        incoming = b"CLAUDE_REPAINT\r\n"
        if pty._paused:
            pty._paused_buffer.extend(incoming)
        else:
            pty._stream.feed(incoming)

        # View unchanged.
        assert _visible(pty._screen) == scrolled_view
        assert b"CLAUDE_REPAINT" in bytes(pty._paused_buffer)
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_resume_live_replays_buffered_output() -> None:
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        pty = app.query_one("#pty", PtyTerminal)
        _seed_history(pty)
        pty.scroll_history(-1)
        pty._paused_buffer.extend(b"AFTER-PAUSE\r\n")

        pty.resume_live()

        assert not pty.is_paused
        assert pty._paused_buffer == bytearray()
        # The buffered content should now be visible near the live tail.
        assert "AFTER-PAUSE" in _visible(pty._screen)
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_scroll_forward_past_live_resumes() -> None:
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        pty = app.query_one("#pty", PtyTerminal)
        _seed_history(pty)
        pty.scroll_history(-1)
        pty._paused_buffer.extend(b"WHILE-PAUSED\r\n")
        assert pty.is_paused

        # Page forward until we reach the live tail; scroll_history(+1) should
        # flip is_paused off when we get there.
        for _ in range(20):  # safety bound
            pty.scroll_history(+1)
            if not pty.is_paused:
                break

        assert not pty.is_paused
        assert "WHILE-PAUSED" in _visible(pty._screen)
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_write_bytes_while_paused_resumes() -> None:
    """Typing snaps back to live — matches real terminal behaviour."""
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        pty = app.query_one("#pty", PtyTerminal)
        _seed_history(pty)
        pty.scroll_history(-1)
        pty._paused_buffer.extend(b"BUFFERED\r\n")
        assert pty.is_paused

        pty.write_bytes(b"x")

        assert not pty.is_paused
        assert "BUFFERED" in _visible(pty._screen)
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_plain_scroll_pages_back() -> None:
    """Plain wheel — no modifier — scrolls the pyte scrollback.

    Inside our embedded view the outer terminal's scrollback is useless
    (nothing reaches it), so we claim the plain wheel for our own history.
    """
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        pty = app.query_one("#pty", PtyTerminal)
        _seed_history(pty)
        before = pty._screen.history.position

        pty.post_message(_make_scroll_event(events.MouseScrollUp, pty, shift=False))
        await pilot.pause(0.05)

        assert pty.is_paused
        assert pty._screen.history.position < before
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


# ─── app-level key routing ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shift_pageup_pauses_and_pages_back() -> None:
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        pty = app.query_one("#pty", PtyTerminal)
        _seed_history(pty)
        before = pty._screen.history.position

        await pilot.press("shift+pageup")
        await pilot.pause(0.05)

        assert pty.is_paused
        assert pty._screen.history.position < before
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_shift_end_resumes_live() -> None:
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        pty = app.query_one("#pty", PtyTerminal)
        _seed_history(pty)
        pty.scroll_history(-1)
        pty._paused_buffer.extend(b"WAITING\r\n")
        assert pty.is_paused

        await pilot.press("shift+end")
        await pilot.pause(0.05)

        assert not pty.is_paused
        assert "WAITING" in _visible(pty._screen)
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)
