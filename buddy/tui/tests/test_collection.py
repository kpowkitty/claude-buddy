"""Tests for the gacha collection model (buddy/collection.py).

Covers the schema, the single-buddy → collection migration, accessors,
and the derived token / shard math. All pure functions — no filesystem.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUDDY = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _BUDDY not in sys.path:
    sys.path.insert(0, _BUDDY)

from collection import (  # noqa: E402
    LEVELS_PER_TOKEN_STEP,
    SHARDS_PER_REDEEM,
    active_buddy,
    add_buddy,
    add_shard,
    all_buddies,
    empty_collection,
    global_level,
    has_species,
    hatches_available,
    migrate,
    redeem_shards,
    set_active,
    shards,
    shards_ready_to_redeem,
    tokens_earned,
)


# ─── migration ───────────────────────────────────────────────────────────────


def test_migrate_empty_returns_empty_collection() -> None:
    assert migrate({}) == empty_collection()
    assert migrate(None) == empty_collection()


def test_migrate_old_single_buddy_wraps_into_collection() -> None:
    old = {
        "species_id": "slime",
        "species_name": "Slime",
        "name": "quine",
        "rarity": "common",
        "level": 4,
        "xp": 120,
        "skills": {"wisdom": 40},
    }
    c = migrate(old)
    assert c["active_id"] == "slime"
    assert "slime" in c["buddies"]
    # The full old dict is preserved as the buddy entry.
    assert c["buddies"]["slime"] == old
    # Starter counts as the first hatch.
    assert c["hatches_performed"] == 1
    assert c["shards"] == 0


def test_migrate_already_collection_shape_is_idempotent() -> None:
    c = {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime", "level": 3}},
        "hatches_performed": 1,
        "shards": 2,
    }
    assert migrate(c) == c
    # And running it twice is a no-op.
    assert migrate(migrate(c)) == c


def test_migrate_fills_missing_counter_fields() -> None:
    c = {"active_id": "slime", "buddies": {"slime": {"species_id": "slime"}}}
    out = migrate(c)
    assert "hatches_performed" in out
    assert out["hatches_performed"] == 1  # one buddy present
    assert out["shards"] == 0


def test_migrate_unknown_shape_falls_back_to_empty() -> None:
    # Junk data shouldn't crash — just return an empty collection.
    assert migrate({"some_unrelated_field": 42}) == empty_collection()


# ─── accessors ───────────────────────────────────────────────────────────────


def test_active_buddy_returns_active_entry() -> None:
    c = {
        "active_id": "ember",
        "buddies": {
            "slime": {"species_id": "slime", "level": 3},
            "ember": {"species_id": "ember", "level": 5},
        },
        "hatches_performed": 2,
        "shards": 0,
    }
    assert active_buddy(c) == {"species_id": "ember", "level": 5}


def test_active_buddy_none_when_no_active() -> None:
    assert active_buddy(empty_collection()) is None


def test_all_buddies_returns_insertion_order() -> None:
    c = {
        "active_id": "slime",
        "buddies": {
            "slime": {"species_id": "slime"},
            "pebble": {"species_id": "pebble"},
        },
        "hatches_performed": 2, "shards": 0,
    }
    assert all_buddies(c) == [{"species_id": "slime"}, {"species_id": "pebble"}]


def test_has_species() -> None:
    c = {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime"}},
        "hatches_performed": 1, "shards": 0,
    }
    assert has_species(c, "slime") is True
    assert has_species(c, "ember") is False


def test_set_active_points_at_new_buddy() -> None:
    c = {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime"}, "ember": {"species_id": "ember"}},
        "hatches_performed": 2, "shards": 0,
    }
    c2 = set_active(c, "ember")
    assert c2["active_id"] == "ember"
    # Original untouched (pure function).
    assert c["active_id"] == "slime"


def test_add_buddy_inserts_and_bumps_hatch_counter() -> None:
    c = empty_collection()
    entry = {"species_id": "slime", "level": 1}
    c2 = add_buddy(c, "slime", entry)
    assert "slime" in c2["buddies"]
    assert c2["hatches_performed"] == 1
    assert c2["active_id"] == "slime"
    assert c["buddies"] == {}  # original untouched


def test_add_buddy_respects_set_active_false() -> None:
    c = {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime"}},
        "hatches_performed": 1, "shards": 0,
    }
    c2 = add_buddy(c, "ember", {"species_id": "ember"}, set_active_to_new=False)
    assert c2["active_id"] == "slime"
    assert c2["hatches_performed"] == 2


# ─── derived economy ─────────────────────────────────────────────────────────


# Helper: level is derived as xp//20 where xp = prompts*2 + tools//3.
# 10 prompts → xp 20 → level 1. So prompts = 10*L gives level L exactly.
def _buddy_at_level(level: int, species_id: str = "slime") -> dict:
    return {
        "species_id": species_id,
        "total_prompts": 10 * level,
        "total_tools": 0,
    }


def test_global_level_single_buddy() -> None:
    c = {
        "active_id": "slime",
        "buddies": {"slime": _buddy_at_level(10)},
        "hatches_performed": 1, "shards": 0,
    }
    assert global_level(c) == 10


def test_global_level_sums_across_buddies() -> None:
    c = {
        "active_id": "slime",
        "buddies": {
            "slime": _buddy_at_level(10),
            "ember": _buddy_at_level(6, "ember"),
        },
        "hatches_performed": 2, "shards": 0,
    }
    assert global_level(c) == 16


def test_tokens_earned_triangular_schedule() -> None:
    """STEP × K(K+1)/2 is the cumulative cost to have earned K tokens."""
    def one_buddy(level: int) -> dict:
        return {
            "active_id": "slime",
            "buddies": {"slime": _buddy_at_level(level)},
            "hatches_performed": 1, "shards": 0,
        }

    # STEP=5: thresholds are 5, 15, 30, 50, 75.
    assert tokens_earned(one_buddy(4)) == 0
    assert tokens_earned(one_buddy(5)) == 1
    assert tokens_earned(one_buddy(14)) == 1
    assert tokens_earned(one_buddy(15)) == 2
    assert tokens_earned(one_buddy(29)) == 2
    assert tokens_earned(one_buddy(30)) == 3
    assert tokens_earned(one_buddy(49)) == 3
    assert tokens_earned(one_buddy(50)) == 4
    assert tokens_earned(one_buddy(75)) == 5


def test_hatches_available_zero_at_install() -> None:
    """Fresh starter — hatches_performed=1, no earned tokens yet. Starter
    is a gift, so hatches_available should be 0 (not -1, not 1)."""
    c = migrate({"species_id": "slime", "level": 1})
    assert c["hatches_performed"] == 1
    assert tokens_earned(c) == 0
    assert hatches_available(c) == 0


def test_hatches_available_earns_at_first_threshold() -> None:
    c = {
        "active_id": "slime",
        "buddies": {"slime": _buddy_at_level(5)},
        "hatches_performed": 1, "shards": 0,
    }
    assert tokens_earned(c) == 1
    assert hatches_available(c) == 1


def test_hatches_available_decrements_after_second_hatch() -> None:
    c = {
        "active_id": "slime",
        "buddies": {
            "slime": _buddy_at_level(5),
            "ember": _buddy_at_level(1, "ember"),
        },
        "hatches_performed": 2, "shards": 0,
    }
    # global 6 → still only 1 token earned (next at 15). available = 1 - 1 = 0.
    assert tokens_earned(c) == 1
    assert hatches_available(c) == 0


def test_hatches_available_accumulates() -> None:
    c = {
        "active_id": "slime",
        "buddies": {"slime": _buddy_at_level(30)},
        "hatches_performed": 1, "shards": 0,
    }
    # global 30 → 3 tokens earned (thresholds 5, 15, 30). starter free.
    assert tokens_earned(c) == 3
    assert hatches_available(c) == 3


def test_hoarding_does_not_accelerate() -> None:
    """The escalation is keyed to (performed + available) = tokens_earned + 1,
    so a hoarder faces the same curve as someone who spent immediately.
    Concretely: at global level 30, you've earned exactly 3 tokens whether
    you spent them or not."""
    hoarder = {
        "active_id": "slime",
        "buddies": {"slime": _buddy_at_level(30)},
        "hatches_performed": 1, "shards": 0,
    }
    spender = {
        "active_id": "d",
        "buddies": {
            "a": _buddy_at_level(10, "a"),
            "b": _buddy_at_level(10, "b"),
            "c": _buddy_at_level(5, "c"),
            "d": _buddy_at_level(5, "d"),
        },
        "hatches_performed": 4, "shards": 0,
    }
    assert tokens_earned(hoarder) == tokens_earned(spender) == 3


def test_hatches_available_never_negative() -> None:
    c = {
        "active_id": "slime",
        "buddies": {"slime": {"species_id": "slime", "level": 1}},
        "hatches_performed": 5,  # somehow
        "shards": 0,
    }
    assert hatches_available(c) == 0


# ─── shards ──────────────────────────────────────────────────────────────────


def test_add_shard_increments() -> None:
    c = empty_collection()
    c = add_shard(c)
    assert shards(c) == 1
    c = add_shard(c, 3)
    assert shards(c) == 4


def test_shards_ready_at_threshold() -> None:
    c = empty_collection()
    for _ in range(SHARDS_PER_REDEEM - 1):
        c = add_shard(c)
    assert shards_ready_to_redeem(c) is False
    c = add_shard(c)
    assert shards_ready_to_redeem(c) is True


def test_redeem_resets_to_zero_at_exactly_five() -> None:
    c = empty_collection()
    for _ in range(SHARDS_PER_REDEEM):
        c = add_shard(c)
    c = redeem_shards(c)
    assert shards(c) == 0


def test_redeem_consumes_five_leaving_overflow() -> None:
    c = empty_collection()
    for _ in range(7):
        c = add_shard(c)
    c = redeem_shards(c)
    # 7 − 5 = 2 left over. (Design could change this to reset; for now overflow
    # is preserved because the accessor just subtracts SHARDS_PER_REDEEM.)
    assert shards(c) == 2


def test_redeem_noop_below_threshold() -> None:
    c = empty_collection()
    c = add_shard(c, 3)
    c2 = redeem_shards(c)
    assert shards(c2) == 3  # unchanged


# ─── constants sanity ────────────────────────────────────────────────────────


def test_constants_are_locked_in() -> None:
    """If these constants change, the economy changes — tests should notice."""
    assert LEVELS_PER_TOKEN_STEP == 5
    assert SHARDS_PER_REDEEM == 5
