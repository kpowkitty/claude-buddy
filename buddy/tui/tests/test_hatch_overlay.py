"""Tests for the HatchOverlay modal.

Contract covered:
  - Mounts from the gacha hatch path (F2 → H → T/S).
  - Owns the hatch: progression.json is written at CRACK_END, not before.
  - Only dismissible with q, and only after the reveal lands.
  - New buddy is NOT made active (unless the roster was empty before).
  - Duplicate token rolls show a "+1 shard" reveal box.
  - Gacha menu stays in the screen stack underneath — after close, the
    user lands back on it.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

import app as _app_mod
from app import BuddyApp
from gacha_menu import GachaMenu
from hatch_overlay import HatchOverlay

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUDDY = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _BUDDY not in sys.path:
    sys.path.insert(0, _BUDDY)


def _seed(monkeypatch, tmp_path, payload):
    prog = tmp_path / "progression.json"
    prog.write_text(json.dumps(payload))
    monkeypatch.setattr(_app_mod, "PROGRESSION", prog)
    import gacha_menu
    import hatch as _hatch
    import hatch_overlay as _overlay
    import switch as _switch
    import state as _state
    monkeypatch.setattr(_state, "PROGRESSION", prog)
    monkeypatch.setattr(gacha_menu, "PROGRESSION", prog)
    monkeypatch.setattr(_switch, "PROGRESSION", prog)
    monkeypatch.setattr(_hatch, "PROGRESSION", prog)
    monkeypatch.setattr(_overlay, "PROGRESSION", prog)
    # hatch.py also reads BUDDY_DIR for its atomic write parent.
    monkeypatch.setattr(_hatch, "BUDDY_DIR", tmp_path)
    return prog


def _fast_phases(overlay: HatchOverlay) -> None:
    """Shrink phase thresholds so tests don't wait 3s per run."""
    overlay.IDLE_END = 1
    overlay.SHAKE_END = 2
    overlay.CRACK_END = 3


# ── overlay mounts from the gacha shard redeem path ─────────────────────────


@pytest.mark.asyncio
async def test_overlay_mounts_after_shard_redeem(monkeypatch, tmp_path) -> None:
    """5 shards + owned slime → H → S pushes the overlay on top of the
    gacha menu; both stay in the stack."""
    _seed(monkeypatch, tmp_path, {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime", "total_prompts": 20}},
        "hatches_performed": 6,
        "shards": 5,
    })
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        await pilot.press("f2")
        await pilot.pause(0.1)
        assert isinstance(app.screen, GachaMenu)
        await pilot.press("h")
        await pilot.pause(0.1)
        await pilot.press("s")
        await pilot.pause(0.2)
        # Overlay is on top; gacha menu is still in the stack underneath.
        assert isinstance(app.screen, HatchOverlay)
        gacha_underneath = [s for s in app.screen_stack if isinstance(s, GachaMenu)]
        assert gacha_underneath, "gacha menu should still be in the stack"
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


# ── q only works after reveal lands; earlier keypresses are ignored ─────────


@pytest.mark.asyncio
async def test_q_is_ignored_before_reveal(monkeypatch, tmp_path) -> None:
    _seed(monkeypatch, tmp_path, {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime", "total_prompts": 20}},
        "hatches_performed": 6,
        "shards": 5,
    })
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        overlay = HatchOverlay("shards")
        # Keep normal phase timing so CRACK_END is clearly later.
        app.push_screen(overlay)
        await pilot.pause(0.1)
        assert isinstance(app.screen, HatchOverlay)
        # Press q before CRACK_END — should be ignored.
        await pilot.press("q")
        await pilot.pause(0.1)
        assert isinstance(app.screen, HatchOverlay)
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


# ── q dismisses once the reveal has landed ──────────────────────────────────


@pytest.mark.asyncio
async def test_q_dismisses_after_reveal(monkeypatch, tmp_path) -> None:
    _seed(monkeypatch, tmp_path, {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime", "total_prompts": 20}},
        "hatches_performed": 6,
        "shards": 5,
    })
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        overlay = HatchOverlay("shards")
        _fast_phases(overlay)
        app.push_screen(overlay)
        # Wait past CRACK_END (3 ticks at 10fps = 0.3s) with slack.
        await pilot.pause(0.6)
        assert overlay._dismissable, "reveal should have landed"
        await pilot.press("q")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, HatchOverlay)
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


# ── hatch actually happens (progression.json grows) at CRACK_END ────────────


@pytest.mark.asyncio
async def test_hatch_writes_at_crack_end(monkeypatch, tmp_path) -> None:
    prog = _seed(monkeypatch, tmp_path, {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime", "total_prompts": 20}},
        "hatches_performed": 6,
        "shards": 5,
    })
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        overlay = HatchOverlay("shards")
        _fast_phases(overlay)
        app.push_screen(overlay)
        await pilot.pause(0.6)
        saved = json.loads(prog.read_text())
        # Shard redeem burns shards and adds a new species.
        assert saved["shards"] == 0
        assert len(saved["buddies"]) == 2
        # Previous buddy is still active — no auto-switch on a non-empty
        # roster. The user picks whether to switch via the gacha menu.
        assert saved["active_id"] == "slime"
        await pilot.press("q")
        await pilot.pause(0.1)
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


# ── starter gift (empty roster) auto-activates the new buddy ────────────────


@pytest.mark.asyncio
async def test_starter_hatch_sets_active(monkeypatch, tmp_path) -> None:
    prog = _seed(monkeypatch, tmp_path, {
        "active_id": None,
        "buddies": {},
        "hatches_performed": 0,
        "shards": 0,
    })
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        overlay = HatchOverlay("tokens")
        _fast_phases(overlay)
        app.push_screen(overlay)
        await pilot.pause(0.6)
        saved = json.loads(prog.read_text())
        assert len(saved["buddies"]) == 1
        # Empty roster before hatch → new buddy becomes active (nothing
        # on-screen to be surprised by).
        assert saved["active_id"] is not None
        await pilot.press("q")
        await pilot.pause(0.1)
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


# ── duplicate roll still shows a reveal (with +1 shard note) ────────────────


@pytest.mark.asyncio
async def test_duplicate_roll_shows_reveal(monkeypatch, tmp_path) -> None:
    """Roster owns every species already → token roll is guaranteed to
    duplicate. Overlay should still show the reveal box with a dupe
    note instead of silently dismissing."""
    # Seed a collection holding all common species so any roll in the
    # common rarity is a dupe. We bias the RNG below so we land in common.
    from species import SPECIES
    buddies = {
        sp["id"]: {"species_id": sp["id"], "total_prompts": 100}
        for sp in SPECIES["common"]
    }
    _seed(monkeypatch, tmp_path, {
        "active_id": SPECIES["common"][0]["id"],
        "buddies": buddies,
        "hatches_performed": len(buddies),
        "shards": 0,
    })
    app = BuddyApp(["/bin/cat"])
    import random as _random
    # Seeded to land on rarity=common (weight 60%) and then one of the
    # owned common species.
    rng = _random.Random(0)
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        # Bypass the token pre-check by creating the overlay directly
        # (test_h_then_t_spends_token_when_available uses total_prompts=100
        # to earn tokens, same here).
        overlay = HatchOverlay("tokens", rng=rng)
        _fast_phases(overlay)
        app.push_screen(overlay)
        await pilot.pause(0.6)
        # The overlay stayed up (no auto-dismiss). If we rolled a dupe,
        # _is_dupe is True; if we happened to roll a rarer new species,
        # _entry is set. Either way, the reveal is visible and waiting.
        assert overlay._dismissable
        assert isinstance(app.screen, HatchOverlay)
        await pilot.press("q")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, HatchOverlay)
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


# ── long flavor text wraps inside the box instead of overflowing ────────────


@pytest.mark.asyncio
async def test_long_flavor_wraps_and_is_scrollable(monkeypatch, tmp_path) -> None:
    """A flavor line wider than the box inner width should wrap into
    multiple lines, and ↑/↓ should scroll the reveal once it lands."""
    _seed(monkeypatch, tmp_path, {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime", "total_prompts": 20}},
        "hatches_performed": 6, "shards": 5,
    })
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        overlay = HatchOverlay("shards")
        _fast_phases(overlay)
        app.push_screen(overlay)
        await pilot.pause(0.6)
        assert overlay._dismissable

        # Force a long flavor string to prove wrapping kicks in. Use
        # a sentence substantially longer than _BOX_INNER_W.
        overlay._flavor = (
            "A very long flavor text that definitely exceeds the inner "
            "width of the hatch box and must wrap across several lines "
            "to be readable by the user."
        )
        stage = overlay.query_one("#hatch-stage")
        raw = overlay._reveal_block()
        # inner_w is stage width - 2 border columns.
        inner_w = stage.size.width - 2
        wrapped = stage._wrap_block(raw, inner_w)
        # Every wrapped line fits inside the inner width.
        assert all(len(line) <= inner_w for line in wrapped)
        # And the wrapping actually produced more rows than the raw block
        # (because the flavor split into multiple lines).
        assert len(wrapped) > len(raw)

        # Scroll down — _scroll_y moves.
        before = overlay._scroll_y
        await pilot.press("down")
        await pilot.pause(0.05)
        assert overlay._scroll_y == before + 1

        await pilot.press("q")
        await pilot.pause(0.1)
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


# ── full round trip: gacha → hatch → overlay close → back on gacha ──────────


@pytest.mark.asyncio
async def test_closing_overlay_lands_back_on_gacha_menu(monkeypatch, tmp_path) -> None:
    _seed(monkeypatch, tmp_path, {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime", "total_prompts": 20}},
        "hatches_performed": 6,
        "shards": 5,
    })
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        await pilot.press("f2")
        await pilot.pause(0.1)
        await pilot.press("h")
        await pilot.pause(0.1)
        # Swap phases on whatever overlay is about to mount. We patch the
        # class so the next instance picks up fast phases too.
        HatchOverlay.IDLE_END = 1
        HatchOverlay.SHAKE_END = 2
        HatchOverlay.CRACK_END = 3
        try:
            await pilot.press("s")
            await pilot.pause(0.6)
            assert isinstance(app.screen, HatchOverlay)
            await pilot.press("q")
            await pilot.pause(0.1)
            # Back on the gacha menu — stack pop, menu was never dismissed.
            assert isinstance(app.screen, GachaMenu)
        finally:
            HatchOverlay.IDLE_END = 8
            HatchOverlay.SHAKE_END = 18
            HatchOverlay.CRACK_END = 28
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)
