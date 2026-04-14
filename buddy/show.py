#!/usr/bin/env python3
"""Print the current buddy's card. Used by `/buddy` with no args."""
from __future__ import annotations

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from hatch import RARITY_COLOR, RESET, BOLD, DIM, format_skills  # noqa: E402
from species import find_species  # noqa: E402

PROGRESSION = pathlib.Path.home() / ".claude" / "buddy" / "progression.json"


def humanize_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s old"
    if seconds < 3600:
        return f"{int(seconds // 60)}m old"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h old"
    return f"{int(seconds // 86400)}d old"


def main() -> int:
    if not PROGRESSION.exists():
        print("You don't have a buddy yet. Run `/buddy hatch` to get one.")
        return 1
    try:
        data = json.loads(PROGRESSION.read_text())
    except json.JSONDecodeError:
        print("Your buddy's save file is corrupted. Run `/buddy forget --confirm` then `/buddy hatch`.")
        return 1
    species_id = data.get("species_id")
    if not species_id:
        print("Your buddy's save file is from an older version. Run `/buddy forget --confirm` then `/buddy hatch`.")
        return 1
    rarity, species = find_species(species_id)
    if species is None:
        print(f"Unknown species id: {species_id}. Run `/buddy forget --confirm` then `/buddy hatch`.")
        return 1

    color = RARITY_COLOR[rarity]
    display_name = data.get("name") or species["name"]
    age = humanize_age(time.time() - data["hatched_at"])

    print()
    print(f"  {BOLD}{color}★ {rarity.upper()} ★{RESET}")
    print()
    for line in species["art"]:
        print(f"  {color}{line}{RESET}")
    print()
    if data.get("name"):
        print(f"  {BOLD}{display_name}{RESET}  {DIM}({species['name']}){RESET}")
    else:
        print(f"  {BOLD}{species['name']}{RESET}")
    print(f"  {DIM}{species['flavor']}{RESET}")
    print(f"  {DIM}{age}{RESET}")
    print()
    for line in format_skills(data["skills"], data["signature_skill"]):
        print(line)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
