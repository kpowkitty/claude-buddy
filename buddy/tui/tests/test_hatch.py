"""Tests for hatch.py's gacha economy.

Covers the two action paths (do_tokens_hatch, do_shard_hatch) against
seeded random numbers so rolls are deterministic. Uses tmp_path to
redirect PROGRESSION so we never touch the real save file.
"""
from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUDDY = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _BUDDY not in sys.path:
    sys.path.insert(0, _BUDDY)

import hatch  # noqa: E402
from collection import (  # noqa: E402
    SHARDS_PER_REDEEM,
    all_buddies,
    empty_collection,
    has_species,
    shards,
)
from species import SPECIES, RARITY_ORDER  # noqa: E402


# ─── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_progression(monkeypatch, tmp_path: Path):
    """Every test gets a throwaway progression.json."""
    monkeypatch.setattr(hatch, "BUDDY_DIR", tmp_path)
    monkeypatch.setattr(hatch, "PROGRESSION", tmp_path / "progression.json")
    yield


def _fixed_rng(species_id: str) -> random.Random:
    """Return an rng seeded to roll exactly `species_id` on the next call.

    Brute force: try seeds until we find one. Deterministic and fast
    because the species pool is small.
    """
    for seed in range(2000):
        r = random.Random(seed)
        _, s = hatch.roll_species(r)
        if s["id"] == species_id:
            return random.Random(seed)
    raise RuntimeError(f"couldn't seed rng to roll {species_id}")


# ─── starter gift: first hatch on empty collection ──────────────────────────


def test_starter_hatch_succeeds_on_empty_collection() -> None:
    rc = hatch.do_tokens_hatch(empty_collection(), _fixed_rng("slime"))
    assert rc == 0
    saved = json.loads(hatch.PROGRESSION.read_text())
    assert saved["active_id"] == "slime"
    assert "slime" in saved["buddies"]
    assert saved["hatches_performed"] == 1


# ─── token gate on subsequent free hatches ──────────────────────────────────


def test_tokens_hatch_refused_when_no_token(capsys) -> None:
    # One buddy, pet-level 1 → global 0.5 → 0 tokens earned, 0 available.
    c = {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime", "level": 1}},
        "hatches_performed": 1, "shards": 0,
    }
    hatch.save_collection(c)
    rc = hatch.do_tokens_hatch(hatch.load_collection(), _fixed_rng("ember"))
    assert rc == 1
    out = capsys.readouterr().out
    # Header explains the failure; the status block includes the gap info.
    assert "No hatches available" in out
    assert "pet-level" in out
    # Full command reference is present so the user doesn't have to dig.
    assert "claude-buddy-hatch --tokens" in out
    assert "claude-buddy-hatch --shards" in out


def test_tokens_hatch_succeeds_when_token_available() -> None:
    # 100 prompts → xp 200 → level 10 → global 10 → ≥1 token earned.
    c = {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime", "total_prompts": 100}},
        "hatches_performed": 1, "shards": 0,
    }
    hatch.save_collection(c)
    rc = hatch.do_tokens_hatch(hatch.load_collection(), _fixed_rng("ember"))
    assert rc == 0
    saved = json.loads(hatch.PROGRESSION.read_text())
    assert "ember" in saved["buddies"]
    assert saved["hatches_performed"] == 2
    assert saved["shards"] == 0


# ─── duplicate handling ─────────────────────────────────────────────────────


def test_duplicate_roll_burns_token_and_grants_shard(capsys) -> None:
    # Have slime; a token ready; roll slime again.
    c = {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime", "total_prompts": 100}},
        "hatches_performed": 1, "shards": 0,
    }
    hatch.save_collection(c)
    rc = hatch.do_tokens_hatch(hatch.load_collection(), _fixed_rng("slime"))
    assert rc == 0
    saved = json.loads(hatch.PROGRESSION.read_text())
    # Token burned (hatches_performed bumped) but NO new buddy added.
    assert saved["hatches_performed"] == 2
    assert len(saved["buddies"]) == 1
    assert saved["shards"] == 1
    out = capsys.readouterr().out
    assert "duplicate" in out.lower()
    assert "shard" in out.lower()


def test_five_duplicates_accumulate_to_redeem_threshold() -> None:
    # Stack five dupes; verify shards reach 5 and user can redeem.
    # 1000 prompts → xp 2000 → level 100 → plenty of tokens.
    c = {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime", "total_prompts": 1000}},
        "hatches_performed": 1, "shards": 0,
    }
    hatch.save_collection(c)
    for _ in range(SHARDS_PER_REDEEM):
        hatch.do_tokens_hatch(hatch.load_collection(), _fixed_rng("slime"))
    saved = json.loads(hatch.PROGRESSION.read_text())
    assert saved["shards"] == SHARDS_PER_REDEEM
    assert len(saved["buddies"]) == 1  # still just slime


# ─── shard redeem path ──────────────────────────────────────────────────────


def test_shard_redeem_requires_five_shards(capsys) -> None:
    c = {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime"}},
        "hatches_performed": 1, "shards": SHARDS_PER_REDEEM - 1,
    }
    hatch.save_collection(c)
    rc = hatch.do_shard_hatch(hatch.load_collection(), random.Random(0))
    assert rc == 1
    out = capsys.readouterr().out
    assert "shards to redeem" in out
    assert "claude-buddy-hatch --tokens" in out  # help block present


def test_shard_redeem_never_rolls_owned_species() -> None:
    c = {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime"}},
        "hatches_performed": 1, "shards": SHARDS_PER_REDEEM,
    }
    hatch.save_collection(c)
    # Even with an rng that would have landed on slime, the filter forces
    # a different species.
    rc = hatch.do_shard_hatch(hatch.load_collection(), _fixed_rng("slime"))
    assert rc == 0
    saved = json.loads(hatch.PROGRESSION.read_text())
    owned = set(saved["buddies"].keys())
    assert "slime" in owned  # still there
    assert len(owned) == 2
    # The new buddy is NOT slime.
    new_ids = owned - {"slime"}
    assert len(new_ids) == 1
    assert saved["shards"] == 0


def test_shard_redeem_refuses_when_collection_complete(capsys) -> None:
    # Own every species.
    all_ids = [s["id"] for r in RARITY_ORDER for s in SPECIES[r]]
    c = {
        "active_id": all_ids[0],
        "buddies": {sid: {"species_id": sid} for sid in all_ids},
        "hatches_performed": len(all_ids),
        "shards": SHARDS_PER_REDEEM,
    }
    hatch.save_collection(c)
    rc = hatch.do_shard_hatch(hatch.load_collection(), random.Random(0))
    assert rc == 1
    # Shards preserved.
    saved = json.loads(hatch.PROGRESSION.read_text())
    assert saved["shards"] == SHARDS_PER_REDEEM
    out = capsys.readouterr().out
    assert "every species" in out
    # Still shows full help even at this dead-end state.
    assert "claude-buddy-hatch" in out


# ─── CLI main() dispatch ────────────────────────────────────────────────────


def test_main_no_mode_flag_prints_usage(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["hatch"])
    rc = hatch.main()
    assert rc == 1
    out = capsys.readouterr().out
    assert "--tokens" in out
    assert "--shards" in out
    # The full help block shows current status too.
    assert "Commands" in out


def test_main_help_flag_prints_status_and_exits_zero(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["hatch", "--help"])
    rc = hatch.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "claude-buddy-hatch --tokens" in out
    assert "F1" in out  # TUI keybinds included in the one-stop help


def test_main_tokens_flag_runs_do_tokens_hatch(monkeypatch) -> None:
    called: dict = {}

    def _stub(c, rng):
        called["ran"] = True
        return 42

    monkeypatch.setattr(sys, "argv", ["hatch", "--tokens"])
    monkeypatch.setattr(hatch, "do_tokens_hatch", _stub)
    rc = hatch.main()
    assert rc == 42
    assert called.get("ran") is True


def test_main_shards_flag_runs_do_shard_hatch(monkeypatch) -> None:
    called: dict = {}

    def _stub(c, rng):
        called["ran"] = True
        return 7

    monkeypatch.setattr(sys, "argv", ["hatch", "--shards"])
    monkeypatch.setattr(hatch, "do_shard_hatch", _stub)
    rc = hatch.main()
    assert rc == 7
    assert called.get("ran") is True


def test_main_both_flags_is_ambiguous(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["hatch", "--tokens", "--shards"])
    rc = hatch.main()
    assert rc == 1
    out = capsys.readouterr().out
    assert "Pick one mode" in out
    assert "--tokens" in out


