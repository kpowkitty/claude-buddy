#!/usr/bin/env python3
"""Hatch a new buddy: roll rarity, pick species, roll skills, save.

Usage:
    python3 hatch.py           # hatch (errors if one exists)
    python3 hatch.py --force   # re-hatch, discarding current buddy
    python3 hatch.py --peek    # roll and print without saving
"""
from __future__ import annotations

import json
import os
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from species import RARITY_WEIGHTS, RARITY_ORDER, SPECIES, SKILLS, roll_skills  # noqa: E402

BUDDY_DIR = pathlib.Path.home() / ".claude" / "buddy"
PROGRESSION = BUDDY_DIR / "progression.json"

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


def write_atomic(path: pathlib.Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


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


def main() -> int:
    force = "--force" in sys.argv
    peek = "--peek" in sys.argv
    rng = random.Random()

    if peek:
        rarity, species = roll_species(rng)
        skills = roll_skills(rng, species, rarity)
        print(render_reveal(rarity, species, skills))
        print("  (peek only — not saved)")
        return 0

    if PROGRESSION.exists() and not force:
        current = json.loads(PROGRESSION.read_text())
        who = current.get("name") or current.get("species_name") or current.get("species_id", "buddy")
        rarity = current.get("rarity", "unknown")
        print(f"You already have a buddy: {who} ({rarity}).")
        print("Run `/buddy forget --confirm` to release them, then `/buddy hatch` again.")
        return 1

    rarity, species = roll_species(rng)
    skills = roll_skills(rng, species, rarity)
    now = time.time()
    data = {
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
    BUDDY_DIR.mkdir(parents=True, exist_ok=True)
    write_atomic(PROGRESSION, data)
    print(render_reveal(rarity, species, skills))
    return 0


if __name__ == "__main__":
    sys.exit(main())
