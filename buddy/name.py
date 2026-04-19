#!/usr/bin/env python3
"""Set your active buddy's name. Usage: python3 name.py <name...>"""
from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cli_help import print_help, print_test_mode_banner  # noqa: E402
from collection import active_buddy, migrate  # noqa: E402

from state import PROGRESSION  # noqa: E402 — honors BUDDY_STATE_DIR


def _load_collection() -> dict | None:
    if not PROGRESSION.exists():
        return None
    try:
        return migrate(json.loads(PROGRESSION.read_text()))
    except json.JSONDecodeError:
        return None


def main() -> int:
    print_test_mode_banner()
    args = sys.argv[1:]
    if not args or args[0] in {"--help", "-h"}:
        print_help(_load_collection(), header="Usage: /buddy name <name>")
        return 0 if args and args[0] in {"--help", "-h"} else 1
    new_name = " ".join(args).strip()
    if not new_name:
        print_help(_load_collection(), header="Name can't be empty.")
        return 1
    if len(new_name) > 40:
        print_help(_load_collection(), header="Name too long (max 40 chars).")
        return 1

    collection = _load_collection()
    if collection is None:
        print_help(None, header="You don't have a buddy yet.")
        return 1
    active_id = collection.get("active_id")
    buddy = active_buddy(collection)
    if not active_id or buddy is None:
        print_help(collection, header="You don't have a buddy yet.")
        return 1

    buddy = dict(buddy)
    buddy["name"] = new_name
    collection["buddies"] = dict(collection.get("buddies", {}))
    collection["buddies"][active_id] = buddy

    tmp = PROGRESSION.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(collection, indent=2))
    os.replace(tmp, PROGRESSION)
    print(f"Named your {buddy.get('species_name', 'buddy')}: {new_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
