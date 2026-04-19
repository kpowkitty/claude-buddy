#!/usr/bin/env python3
"""Switch the active buddy. Usage: python3 switch.py <name-or-species>

Matches by custom name first, then by species_id. Case-insensitive. If the
identifier is ambiguous (two buddies share it), lists the candidates and
bails rather than guessing.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cli_help import print_help, print_test_mode_banner  # noqa: E402
from collection import active_buddy, all_buddies, migrate  # noqa: E402

from state import PROGRESSION  # noqa: E402 — honors BUDDY_STATE_DIR


def _load_collection() -> dict | None:
    if not PROGRESSION.exists():
        return None
    try:
        return migrate(json.loads(PROGRESSION.read_text()))
    except json.JSONDecodeError:
        return None


def _find_matches(collection: dict, query: str) -> list[tuple[str, dict]]:
    """Return (buddy_id, entry) pairs whose name or species_id matches `query`
    (case-insensitive). The buddy_id is the dict key in collection['buddies']."""
    q = query.strip().lower()
    matches: list[tuple[str, dict]] = []
    for buddy_id, entry in collection.get("buddies", {}).items():
        name = (entry.get("name") or "").strip().lower()
        species_id = (entry.get("species_id") or "").strip().lower()
        if q in {name, species_id}:
            matches.append((buddy_id, entry))
    return matches


def switch_to(buddy_id: str) -> bool:
    """Direct switch for non-CLI callers (e.g. the TUI gacha menu).

    Writes progression.json with `buddy_id` as active. Returns True on
    success, False if the buddy_id doesn't exist in the collection or
    the save file is missing.
    """
    collection = _load_collection()
    if collection is None or buddy_id not in collection.get("buddies", {}):
        return False
    if collection.get("active_id") == buddy_id:
        return True  # already active, no write needed
    collection = dict(collection)
    collection["active_id"] = buddy_id
    tmp = PROGRESSION.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(collection, indent=2))
    os.replace(tmp, PROGRESSION)
    return True


def main() -> int:
    print_test_mode_banner()
    args = sys.argv[1:]
    collection = _load_collection()

    if not args or args[0] in {"--help", "-h"}:
        print_help(collection, header="Usage: /buddy switch <name-or-species>")
        # --help exits 0; bare invocation exits 1 so callers can detect the miss.
        return 0 if args and args[0] in {"--help", "-h"} else 1

    if collection is None or not all_buddies(collection):
        print_help(None, header="You don't have any buddies to switch between.")
        return 1

    query = " ".join(args).strip()
    matches = _find_matches(collection, query)

    if not matches:
        header = f"No buddy matches '{query}'."
        print_help(collection, header=header)
        return 1

    if len(matches) > 1:
        names = ", ".join(
            f"{e.get('name') or '?'} ({e.get('species_id')})" for _, e in matches
        )
        print_help(
            collection,
            header=f"Ambiguous — '{query}' matches: {names}. Try the species id.",
        )
        return 1

    buddy_id, entry = matches[0]
    if collection.get("active_id") == buddy_id:
        print_help(
            collection,
            header=f"{entry.get('name') or entry.get('species_name')} is already active.",
        )
        return 0

    collection = dict(collection)
    collection["active_id"] = buddy_id
    tmp = PROGRESSION.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(collection, indent=2))
    os.replace(tmp, PROGRESSION)
    who = entry.get("name") or entry.get("species_name") or entry.get("species_id", "buddy")
    print(f"Switched to {who}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
