"""Gacha collection model — owns progression.json's schema.

One user can have many buddies. progression.json stores them as a dict keyed
by a stable buddy_id, plus an `active_id` naming the one currently showing in
the TUI, plus the counters that drive the hatch-token + duplicate-shard
economy.

Old single-buddy progression files are silently migrated on first read: the
top-level buddy fields are moved into a single entry keyed by species_id,
and `active_id` is set to point at it. Callers see the same values via
`active_buddy()`, so nothing downstream needs to know the file changed.

Derived values (global_level, tokens_earned, etc.) are NEVER persisted —
they're computed from the stored buddies on demand.
"""
from __future__ import annotations

import math
import time
from typing import Optional

# ── economy constants (tuneable) ─────────────────────────────────────────────

GLOBAL_LEVEL_RATIO = 0.5        # 1 pet-level → 0.5 global levels
LEVELS_PER_TOKEN = 20           # earn a hatch token every N global levels
SHARDS_PER_REDEEM = 5           # duplicate shards → 1 guaranteed new-species roll


# ── schema shape ─────────────────────────────────────────────────────────────

def empty_collection() -> dict:
    """Shape of a freshly-initialised progression file."""
    return {
        "active_id": None,
        "buddies": {},
        "hatches_performed": 0,
        "shards": 0,
    }


def migrate(raw: dict) -> dict:
    """Return a collection-shaped dict from whatever `raw` looks like.

    - Empty / missing → empty_collection()
    - Already in collection shape (has `buddies`) → returned as-is.
    - Old single-buddy shape (has `species_id` at top level) → wrapped.

    The migration is idempotent: calling migrate() on a migrated dict is a
    no-op. Safe to run on every read.
    """
    if not isinstance(raw, dict) or not raw:
        return empty_collection()
    if "buddies" in raw and "active_id" in raw:
        # Already migrated. Just ensure counters exist.
        out = dict(raw)
        out.setdefault("hatches_performed", len(out.get("buddies", {})))
        out.setdefault("shards", 0)
        out.setdefault("buddies", {})
        return out
    # Old shape: top-level species_id means the whole dict IS one buddy.
    if "species_id" in raw:
        buddy_id = raw["species_id"]
        buddies = {buddy_id: dict(raw)}
        return {
            "active_id": buddy_id,
            "buddies": buddies,
            "hatches_performed": 1,  # they hatched once (the starter)
            "shards": 0,
        }
    # Unknown shape — give up gracefully.
    return empty_collection()


def ensure_first_seen(collection: dict) -> tuple[dict, bool]:
    """Stamp first_seen_ts on any buddy that pre-dates the field.

    Returns (collection, changed). `changed` is True if anything was
    backfilled — callers should persist the result to avoid drift (a
    re-read would otherwise re-stamp with a new `now`, resetting the
    time-with-buddy counter every tick).

    We can't recover the real hatch time, so "now" is our floor — the
    counter starts ticking forward from the first time a session sees
    the buddy.
    """
    now = time.time()
    changed = False
    buddies = dict(collection.get("buddies") or {})
    for buddy_id, buddy in list(buddies.items()):
        if not isinstance(buddy, dict):
            continue
        if not buddy.get("first_seen_ts"):
            buddy = dict(buddy)
            buddy["first_seen_ts"] = now
            buddies[buddy_id] = buddy
            changed = True
    if changed:
        collection = dict(collection)
        collection["buddies"] = buddies
    return collection, changed


# ── accessors ────────────────────────────────────────────────────────────────

def active_buddy(collection: dict) -> Optional[dict]:
    """Return the currently-active buddy entry, or None if there is none.

    The returned dict is the same flat shape that old single-buddy code
    expected (species_id, name, level, xp, skills, signature_skill, etc.).
    """
    active_id = collection.get("active_id")
    if not active_id:
        return None
    return collection.get("buddies", {}).get(active_id)


def all_buddies(collection: dict) -> list[dict]:
    """Return every buddy entry in roster order (insertion order of dict keys)."""
    return list(collection.get("buddies", {}).values())


def has_species(collection: dict, species_id: str) -> bool:
    """True if the user already owns this species."""
    for buddy in all_buddies(collection):
        if buddy.get("species_id") == species_id:
            return True
    return False


def set_active(collection: dict, buddy_id: str) -> dict:
    """Return a copy of `collection` with `active_id` pointing at buddy_id.

    Caller is responsible for verifying buddy_id exists in `buddies` first.
    """
    out = dict(collection)
    out["active_id"] = buddy_id
    return out


def add_buddy(collection: dict, buddy_id: str, entry: dict, *, set_active_to_new: bool = True) -> dict:
    """Return a copy of `collection` with `entry` inserted under `buddy_id`.

    Increments `hatches_performed` (every hatch counts, including the starter).
    """
    out = dict(collection)
    buddies = dict(out.get("buddies", {}))
    buddies[buddy_id] = entry
    out["buddies"] = buddies
    out["hatches_performed"] = int(out.get("hatches_performed", 0)) + 1
    if set_active_to_new:
        out["active_id"] = buddy_id
    return out


# ── derived values (pure functions of the stored collection) ─────────────────

def global_level(collection: dict) -> float:
    """sum of every buddy's level × GLOBAL_LEVEL_RATIO.

    Float so small increments (1 pet-level → 0.5 global) are representable.
    """
    total = sum(int(b.get("level", 1)) for b in all_buddies(collection))
    return total * GLOBAL_LEVEL_RATIO


def tokens_earned(collection: dict) -> int:
    """Total hatch tokens the user has ever earned via leveling.

    Starter is a gift, so `hatches_available` adds +1 to offset the
    starter-incremented `hatches_performed`. That accounting lives in
    `hatches_available`, not here — this is just the earned count.
    """
    return int(math.floor(global_level(collection) / LEVELS_PER_TOKEN))


def hatches_available(collection: dict) -> int:
    """Hatch tokens the user can spend right now.

    Formula: earned - (performed - 1). The `-1` acknowledges the starter as
    a gift that doesn't consume against the earned budget.
    """
    performed = int(collection.get("hatches_performed", 0))
    available = tokens_earned(collection) - max(0, performed - 1)
    return max(0, available)


def shards(collection: dict) -> int:
    return int(collection.get("shards", 0))


def shards_ready_to_redeem(collection: dict) -> bool:
    return shards(collection) >= SHARDS_PER_REDEEM


def add_shard(collection: dict, n: int = 1) -> dict:
    out = dict(collection)
    out["shards"] = shards(out) + n
    return out


def redeem_shards(collection: dict) -> dict:
    """Consume SHARDS_PER_REDEEM shards. Caller decides what the redemption
    produces (typically: a guaranteed-new-species hatch).
    """
    if not shards_ready_to_redeem(collection):
        return dict(collection)
    out = dict(collection)
    out["shards"] = max(0, shards(out) - SHARDS_PER_REDEEM)
    return out
