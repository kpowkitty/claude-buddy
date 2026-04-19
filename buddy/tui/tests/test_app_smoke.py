"""End-to-end smoke tests for BuddyApp using Textual's pilot harness.

We embed a no-op command (/bin/echo) instead of claude — this is structural
verification only (mounts cleanly, key press doesn't crash, quit works).
Real-Claude testing is manual.
"""
from __future__ import annotations

import pytest

from app import BuddyApp
from habitat import Habitat


@pytest.mark.asyncio
async def test_app_mounts_without_crashing() -> None:
    app = BuddyApp(["/bin/echo", "hello"])
    async with app.run_test() as pilot:
        # Give the pty a moment to spawn + emit output.
        await pilot.pause(0.2)
        # App is still running.
        assert app.is_running


@pytest.mark.asyncio
async def test_app_quits_on_ctrl_q() -> None:
    app = BuddyApp(["/bin/echo", "hi"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)
    # Exited cleanly — context manager resolved without exception.


@pytest.mark.asyncio
async def test_app_handles_printable_key_without_crashing() -> None:
    app = BuddyApp(["/bin/cat"])  # cat echoes stdin; stays alive
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        # Punctuation was the bug we're defending against.
        await pilot.press("a")
        await pilot.press("comma")
        await pilot.press("full_stop")
        await pilot.pause(0.1)
        assert app.is_running
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_habitat_and_children_are_transparent() -> None:
    """The Habitat column and its sub-widgets must all be transparent so
    the user's terminal background (wallpaper, opacity, theme) shows
    through and the pane matches the embedded Claude pane visually.

    If any of these paint an opaque bg, the habitat column "punches out"
    a solid rectangle against a translucent terminal."""
    from habitat import Bubble, SpritePanel

    app = BuddyApp(["/bin/echo", "x"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        habitat = app.query_one(Habitat)
        sprite = app.query_one(SpritePanel)
        bubble = app.query_one(Bubble)
        assert habitat.styles.background.a == 0, (
            f"Habitat should be transparent, got {habitat.styles.background!r}"
        )
        assert sprite.styles.background.a == 0, (
            f"SpritePanel should be transparent, got {sprite.styles.background!r}"
        )
        assert bubble.styles.background.a == 0, (
            f"Bubble should be transparent, got {bubble.styles.background!r}"
        )
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_claude_readline_hotkeys_pass_through(monkeypatch, tmp_path) -> None:
    """The whole point of moving app hotkeys to function keys: Claude's own
    readline-style Ctrl keys (Ctrl+P previous prompt, Ctrl+B backward-char,
    Ctrl+S search, etc.) must reach Claude unchanged."""
    import json
    import app as _app_mod
    from pty_terminal import PtyTerminal

    prog_path = tmp_path / "progression.json"
    prog_path.write_text(json.dumps({
        "active_id": "kitsune",
        "buddies": {"kitsune": {"species_id": "kitsune"}},
        "hatches_performed": 1, "shards": 0,
    }))
    monkeypatch.setattr(_app_mod, "PROGRESSION", prog_path)

    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        pty = app.query_one("#pty", PtyTerminal)
        writes: list[bytes] = []
        pty.write_bytes = lambda data: writes.append(data)  # type: ignore[assignment]

        for key, expected in [
            ("ctrl+p", b"\x10"),   # Claude: previous prompt
            ("ctrl+b", b"\x02"),   # readline: backward-char
            ("ctrl+s", b"\x13"),   # readline: forward-search
            ("ctrl+r", b"\x12"),   # readline: reverse-search
        ]:
            await pilot.press(key)
            await pilot.pause(0.05)
            assert expected in b"".join(writes), (
                f"{key} didn't reach Claude as {expected!r}; writes={writes!r}"
            )

        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_f1_pets_buddy(monkeypatch, tmp_path) -> None:
    """F1 replaces Ctrl+P as the pet hotkey. Verify it reaches action_pet."""
    import json
    import app as _app_mod

    prog_path = tmp_path / "progression.json"
    prog_path.write_text(json.dumps({
        "active_id": "kitsune",
        "buddies": {"kitsune": {"species_id": "kitsune", "pets_received": 0}},
        "hatches_performed": 1, "shards": 0,
    }))
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    monkeypatch.setattr(_app_mod, "PROGRESSION", prog_path)
    monkeypatch.setattr(_app_mod, "STATE", state_path)

    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        await pilot.press("f1")
        await pilot.pause(0.1)
        data = json.loads(prog_path.read_text())
        assert data["buddies"]["kitsune"].get("pets_received", 0) == 1
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_toggle_habitat_doesnt_crash() -> None:
    app = BuddyApp(["/bin/echo", "x"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        await pilot.press("f4")
        await pilot.pause(0.1)
        await pilot.press("f4")
        await pilot.pause(0.1)
        assert app.is_running
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)
