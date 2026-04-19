#!/usr/bin/env python3
"""Print the current buddy's card. Used by `/buddy` with no args."""
from __future__ import annotations

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cli_help import print_help, print_test_mode_banner  # noqa: E402
from collection import active_buddy, migrate  # noqa: E402
from hatch import RARITY_COLOR, RESET, BOLD, DIM, format_skills  # noqa: E402
from species import find_species  # noqa: E402

from state import PROGRESSION  # noqa: E402 — honors BUDDY_STATE_DIR


def humanize_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s old"
    if seconds < 3600:
        return f"{int(seconds // 60)}m old"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h old"
    return f"{int(seconds // 86400)}d old"


def main() -> int:
    print_test_mode_banner()
    if set(sys.argv[1:]) & {"--help", "-h"}:
        collection = None
        if PROGRESSION.exists():
            try:
                collection = migrate(json.loads(PROGRESSION.read_text()))
            except json.JSONDecodeError:
                pass
        print_help(collection)
        return 0
    if not PROGRESSION.exists():
        print_help(None, header="You don't have a buddy yet.")
        return 1
    try:
        raw = json.loads(PROGRESSION.read_text())
    except json.JSONDecodeError:
        print_help(None, header="Your buddy's save file is corrupted. Run `/buddy forget --confirm`, then hatch.")
        return 1
    collection = migrate(raw)
    data = active_buddy(collection) or {}
    species_id = data.get("species_id")
    if not species_id:
        print_help(collection, header="Your save file has no active buddy.")
        return 1
    rarity, species = find_species(species_id)
    if species is None:
        print_help(collection, header=f"Unknown species id: {species_id}.")
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
