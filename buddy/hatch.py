#!/usr/bin/env python3
"""Hatch a new buddy.

Usage:
    python3 hatch.py --tokens    # spend one hatch token from your economy
    python3 hatch.py --shards    # spend 5 duplicate shards for a guaranteed
                                  # new species (never rolls a species you
                                  # already own)
    python3 hatch.py             # no-op: prints usage and exits

The economy:
  * Each pet level contributes 0.5 toward your global level.
  * Every 20 global levels earns 1 hatch token (accumulates).
  * Rolling a species you already own on --tokens still burns the token but
    converts into 1 duplicate shard. 5 shards can be redeemed via --shards
    for a roll guaranteed to be a species you don't already own.
  * The very first hatch (empty collection) is a gift — no token needed.
"""
from __future__ import annotations

import json
import os
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cli_help import print_help, print_test_mode_banner  # noqa: E402
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
    shards,
    tokens_earned,
)
from species import RARITY_WEIGHTS, RARITY_ORDER, SPECIES, SKILLS, roll_skills  # noqa: E402

from state import BUDDY_DIR, PROGRESSION  # noqa: E402 — honors BUDDY_STATE_DIR

RARITY_COLOR = {
    "common": "\033[37m",
    "uncommon": "\033[32m",
    "rare": "\033[34m",
    "epic": "\033[35m",
    "legendary": "\033[33m",
}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


# ─── rolling ────────────────────────────────────────────────────────────────


def roll_rarity(rng: random.Random) -> str:
    total = sum(RARITY_WEIGHTS.values())
    pick = rng.uniform(0, total)
    cum = 0.0
    for rarity in RARITY_ORDER:
        cum += RARITY_WEIGHTS[rarity]
        if pick <= cum:
            return rarity
    return RARITY_ORDER[-1]


def roll_species(rng: random.Random):
    rarity = roll_rarity(rng)
    species = rng.choice(SPECIES[rarity])
    return rarity, species


def roll_species_excluding(rng: random.Random, owned: set[str]):
    """Roll until we land on a species NOT in `owned`. Rolls rarity
    each attempt, so rarity odds still apply — just filtered.

    Assumes at least one species exists outside `owned`; callers should
    check before invoking.
    """
    # Safety bound in case of pathological inputs.
    for _ in range(500):
        rarity, species = roll_species(rng)
        if species["id"] not in owned:
            return rarity, species
    # Fallback: pick any unowned species deterministically so we never hang.
    for rarity in RARITY_ORDER:
        for species in SPECIES[rarity]:
            if species["id"] not in owned:
                return rarity, species
    raise RuntimeError("no unowned species to roll")


# ─── persistence ────────────────────────────────────────────────────────────


def write_atomic(path: pathlib.Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def load_collection() -> dict:
    if not PROGRESSION.exists():
        return empty_collection()
    try:
        return migrate(json.loads(PROGRESSION.read_text()))
    except json.JSONDecodeError:
        return empty_collection()


def save_collection(collection: dict) -> None:
    BUDDY_DIR.mkdir(parents=True, exist_ok=True)
    write_atomic(PROGRESSION, collection)


# ─── output formatting ──────────────────────────────────────────────────────


def format_skills(skills: dict, signature: str) -> list[str]:
    width = max(len(s) for s in SKILLS)
    lines = []
    for skill in SKILLS:
        value = skills[skill]
        bar_len = 20
        filled = int(round(value / 100 * bar_len))
        bar = "█" * filled + "░" * (bar_len - filled)
        marker = " ★" if skill == signature else "  "
        lines.append(f"  {skill.ljust(width)}  {bar}  {value:3d}{marker}")
    return lines


def render_reveal(rarity: str, species: dict, skills: dict) -> str:
    color = RARITY_COLOR[rarity]
    out = [
        "",
        f"  {BOLD}{color}★ {rarity.upper()} ★{RESET}",
        "",
    ]
    for art_line in species["art"]:
        out.append(f"  {color}{art_line}{RESET}")
    out += [
        "",
        f"  {BOLD}{species['name']}{RESET}",
        f"  {DIM}{species['flavor']}{RESET}",
        "",
    ]
    out.extend(format_skills(skills, species["signature"]))
    out.append("")
    return "\n".join(out)


def _next_token_message(collection: dict) -> str:
    """Human-friendly 'you're N pet-levels away from the next token' line.

    Global level = sum of pet levels across the roster. Tokens follow a
    triangular schedule: the (K+1)-th token is awarded when global level
    reaches STEP × (K+1)(K+2)/2.
    """
    gl = global_level(collection)
    earned = tokens_earned(collection)
    next_token_at = LEVELS_PER_TOKEN_STEP * (earned + 1) * (earned + 2) // 2
    levels_needed = max(0, next_token_at - gl)
    return (
        f"Your global level is {gl}. You've earned {earned} token(s) so far. "
        f"The next token unlocks in ~{levels_needed} more pet-level(s)."
    )


# ─── the actual hatch actions ───────────────────────────────────────────────


def _entry_for(species: dict, rarity: str, skills: dict) -> dict:
    now = time.time()
    return {
        "species_id": species["id"],
        "species_name": species["name"],
        "rarity": rarity,
        "flavor": species["flavor"],
        "signature_skill": species["signature"],
        "skills": skills,
        "name": None,
        "hatched_at": now,
        "first_seen": now,
        "total_prompts": 0,
        "total_tools": 0,
        "stage": "baby",
    }


def do_tokens_hatch(collection: dict, rng: random.Random) -> int:
    """Spend a token (or the starter gift) to roll. Dupes burn the token
    and grant 1 shard. Mutates `collection` and writes on success."""
    is_starter = len(all_buddies(collection)) == 0
    if not is_starter and hatches_available(collection) <= 0:
        print_help(collection, header="No hatches available yet.")
        return 1

    rarity, species = roll_species(rng)
    skills = roll_skills(rng, species, rarity)

    if has_species(collection, species["id"]):
        # Dupe! Burn the token (bump hatches_performed to match), +1 shard.
        collection = dict(collection)
        collection["hatches_performed"] = int(collection.get("hatches_performed", 0)) + 1
        collection = add_shard(collection, 1)
        save_collection(collection)
        color = RARITY_COLOR[rarity]
        print()
        print(f"  {color}{species['name']}{RESET} — {BOLD}duplicate!{RESET}")
        print(f"  {DIM}+1 shard ({shards(collection)}/{SHARDS_PER_REDEEM} toward a guaranteed new species){RESET}")
        print()
        _print_post_hatch_status(collection)
        return 0

    # Brand new species → add buddy (this also bumps hatches_performed).
    entry = _entry_for(species, rarity, skills)
    collection = add_buddy(collection, species["id"], entry)
    save_collection(collection)
    print(render_reveal(rarity, species, skills))
    _print_post_hatch_status(collection)
    return 0


def _print_post_hatch_status(collection: dict) -> None:
    """Brief after-hatch summary: tokens left + shard progress. Full help
    is reserved for error paths."""
    avail = hatches_available(collection)
    sh = shards(collection)
    parts = []
    if avail > 0:
        parts.append(f"{avail} more hatch(es) ready")
    if sh >= SHARDS_PER_REDEEM:
        parts.append(f"{sh} shards — --shards hatch available!")
    elif sh > 0:
        parts.append(f"{sh}/{SHARDS_PER_REDEEM} shards")
    if parts:
        print(f"  {DIM}{'  ·  '.join(parts)}{RESET}")
        print()


def do_shard_hatch(collection: dict, rng: random.Random) -> int:
    """Spend SHARDS_PER_REDEEM shards for a guaranteed-new-species roll."""
    if shards(collection) < SHARDS_PER_REDEEM:
        print_help(
            collection,
            header=f"You need {SHARDS_PER_REDEEM} shards to redeem — you have {shards(collection)}.",
        )
        return 1

    owned = {b.get("species_id") for b in all_buddies(collection)}
    total_species = sum(len(SPECIES[r]) for r in RARITY_ORDER)
    if len(owned) >= total_species:
        print_help(
            collection,
            header=f"You already own every species. Your {shards(collection)} shard(s) stay on the shelf.",
        )
        return 1

    rarity, species = roll_species_excluding(rng, owned)
    skills = roll_skills(rng, species, rarity)
    collection = redeem_shards(collection)
    entry = _entry_for(species, rarity, skills)
    collection = add_buddy(collection, species["id"], entry)
    save_collection(collection)
    print(f"  {DIM}(redeemed {SHARDS_PER_REDEEM} shards){RESET}")
    print(render_reveal(rarity, species, skills))
    _print_post_hatch_status(collection)
    return 0


# ─── silent helpers for callers (e.g. TUI gacha menu) ──────────────────────


def spend_token_hatch(rng: random.Random | None = None) -> tuple[bool, str, dict | None]:
    """Spend one hatch token (or the starter gift) for a random roll.

    Silent wrapper around do_tokens_hatch for the TUI. Returns (ok,
    message, entry). Dupes count as ok=True since the token was spent
    and a shard was granted — the message explains. Writes
    progression.json on success.
    """
    rng = rng or random.Random()
    collection = load_collection()
    is_starter = len(all_buddies(collection)) == 0
    if not is_starter and hatches_available(collection) <= 0:
        return False, "No hatches available yet.", None
    rarity, species = roll_species(rng)
    skills = roll_skills(rng, species, rarity)
    if has_species(collection, species["id"]):
        collection = dict(collection)
        collection["hatches_performed"] = int(collection.get("hatches_performed", 0)) + 1
        collection = add_shard(collection, 1)
        save_collection(collection)
        return True, f"{species['name']} — duplicate! +1 shard.", None
    entry = _entry_for(species, rarity, skills)
    collection = add_buddy(collection, species["id"], entry)
    save_collection(collection)
    return True, f"Hatched {species['name']}!", entry


def redeem_shards_hatch(rng: random.Random | None = None) -> tuple[bool, str, dict | None]:
    """Spend SHARDS_PER_REDEEM shards for a guaranteed-new-species roll.

    Returns (ok, message, entry):
      ok=True  → shards were spent; `entry` is the new buddy dict.
      ok=False → shards insufficient OR collection already full; entry=None.

    Silent wrapper around do_shard_hatch for non-CLI callers. Writes
    progression.json on success.
    """
    rng = rng or random.Random()
    collection = load_collection()
    if shards(collection) < SHARDS_PER_REDEEM:
        return False, f"Need {SHARDS_PER_REDEEM} shards (have {shards(collection)}).", None
    owned = {b.get("species_id") for b in all_buddies(collection)}
    total_species = sum(len(SPECIES[r]) for r in RARITY_ORDER)
    if len(owned) >= total_species:
        return False, "You already own every species.", None
    rarity, species = roll_species_excluding(rng, owned)
    skills = roll_skills(rng, species, rarity)
    collection = redeem_shards(collection)
    entry = _entry_for(species, rarity, skills)
    collection = add_buddy(collection, species["id"], entry)
    save_collection(collection)
    name = species["name"]
    return True, f"Hatched {name}!", entry


# ─── entry point ────────────────────────────────────────────────────────────


def main() -> int:
    print_test_mode_banner()  # loud signal; may also print via print_help paths
    args = set(sys.argv[1:])
    rng = random.Random()

    if args & {"--help", "-h"}:
        print_help(load_collection())
        return 0

    # Mutual exclusion: require exactly one mode flag.
    mode_flags = args & {"--tokens", "--shards"}
    if len(mode_flags) != 1:
        if mode_flags:
            header = "Pick one mode: --tokens OR --shards (not both)."
        else:
            header = "Which hatch? Pass --tokens or --shards."
        print_help(load_collection(), header=header)
        return 1

    collection = load_collection()

    if "--tokens" in mode_flags:
        return do_tokens_hatch(collection, rng)
    if "--shards" in mode_flags:
        return do_shard_hatch(collection, rng)

    print_help(load_collection())  # unreachable
    return 1


if __name__ == "__main__":
    sys.exit(main())
