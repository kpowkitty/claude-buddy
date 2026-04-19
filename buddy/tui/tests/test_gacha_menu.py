"""Tests for the F2 gacha collection menu.

Covers: opens on F2, shows one slot per species, highlights active buddy,
switches via Enter, closes on Escape, redeems shards via H when ≥5.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

import app as _app_mod
from app import BuddyApp
from gacha_menu import GachaMenu, _Slot

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUDDY = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _BUDDY not in sys.path:
    sys.path.insert(0, _BUDDY)

from species import SPECIES, RARITY_ORDER  # noqa: E402


def _seed(monkeypatch, tmp_path, payload):
    prog = tmp_path / "progression.json"
    prog.write_text(json.dumps(payload))
    monkeypatch.setattr(_app_mod, "PROGRESSION", prog)
    # gacha_menu, switch, hatch all read PROGRESSION from state.py — patch
    # the ones it actually uses.
    import gacha_menu
    import hatch as _hatch
    import switch as _switch
    import state as _state
    monkeypatch.setattr(_state, "PROGRESSION", prog)
    monkeypatch.setattr(gacha_menu, "PROGRESSION", prog)
    monkeypatch.setattr(_switch, "PROGRESSION", prog)
    monkeypatch.setattr(_hatch, "PROGRESSION", prog)
    return prog


@pytest.mark.asyncio
async def test_f2_opens_gacha_menu(monkeypatch, tmp_path) -> None:
    _seed(monkeypatch, tmp_path, {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime", "species_name": "Slime", "level": 3}},
        "hatches_performed": 1, "shards": 0,
    })
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        assert not isinstance(app.screen, GachaMenu)
        await pilot.press("f2")
        await pilot.pause(0.1)
        assert isinstance(app.screen, GachaMenu)
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, GachaMenu)
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_menu_has_slot_per_species(monkeypatch, tmp_path) -> None:
    _seed(monkeypatch, tmp_path, {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime", "level": 1}},
        "hatches_performed": 1, "shards": 0,
    })
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        await pilot.press("f2")
        await pilot.pause(0.1)
        menu = app.screen
        assert isinstance(menu, GachaMenu)
        # One slot per species across all rarities.
        total_species = sum(len(SPECIES[r]) for r in RARITY_ORDER)
        slots = list(menu.query(_Slot))
        assert len(slots) == total_species
        # Only slime is filled; active.
        filled = [s for s in slots if s.filled]
        assert len(filled) == 1
        assert filled[0].species_id == "slime"
        assert filled[0].active is True
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_enter_on_another_filled_slot_switches(monkeypatch, tmp_path) -> None:
    prog = _seed(monkeypatch, tmp_path, {
        "active_id": "slime",
        "buddies": {
            "slime": {"species_id": "slime", "species_name": "Slime", "level": 3},
            "ember": {"species_id": "ember", "species_name": "Ember", "level": 2},
        },
        "hatches_performed": 2, "shards": 0,
    })
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        await pilot.press("f2")
        await pilot.pause(0.1)
        menu = app.screen
        assert isinstance(menu, GachaMenu)

        # Manually place cursor on ember's slot.
        target = None
        for ry, row in enumerate(menu._rows):
            for rx, slot in enumerate(row):
                if slot.species_id == "ember":
                    target = (ry, rx)
                    break
        assert target is not None
        menu._move_cursor(target)
        await pilot.press("enter")
        await pilot.pause(0.1)

        saved = json.loads(prog.read_text())
        assert saved["active_id"] == "ember"
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_h_key_redeems_shards_when_available(monkeypatch, tmp_path) -> None:
    prog = _seed(monkeypatch, tmp_path, {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime", "level": 2}},
        "hatches_performed": 6, "shards": 5,
    })
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        await pilot.press("f2")
        await pilot.pause(0.1)
        await pilot.press("h")
        await pilot.pause(0.1)

        saved = json.loads(prog.read_text())
        # A new buddy should have been added (guaranteed-new-species roll).
        assert len(saved["buddies"]) == 2
        # Shards consumed.
        assert saved["shards"] == 0
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)


@pytest.mark.asyncio
async def test_h_key_noop_without_enough_shards(monkeypatch, tmp_path) -> None:
    prog = _seed(monkeypatch, tmp_path, {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime", "level": 2}},
        "hatches_performed": 1, "shards": 2,
    })
    app = BuddyApp(["/bin/cat"])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        await pilot.press("f2")
        await pilot.pause(0.1)
        await pilot.press("h")
        await pilot.pause(0.1)

        saved = json.loads(prog.read_text())
        # Unchanged.
        assert len(saved["buddies"]) == 1
        assert saved["shards"] == 2
        await pilot.press("ctrl+q")
        await pilot.pause(0.1)
