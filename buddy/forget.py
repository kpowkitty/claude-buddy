#!/usr/bin/env python3
"""Release your active buddy. Usage: python3 forget.py --confirm

Only releases the ACTIVE buddy. If you have others in your collection, one
of them becomes the new active buddy. If they were your last, the whole
progression file is removed.
"""
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
    args = set(sys.argv[1:])
    if args & {"--help", "-h"}:
        print_help(_load_collection(), header="Releases your active buddy.")
        return 0
    if "--confirm" not in args:
        print_help(
            _load_collection(),
            header="This will permanently release your active buddy. Re-run with --confirm.",
        )
        return 1
    if not PROGRESSION.exists():
        print_help(None, header="No buddy to release.")
        return 0

    collection = migrate(json.loads(PROGRESSION.read_text()))
    active_id = collection.get("active_id")
    buddy = active_buddy(collection)
    if not active_id or buddy is None:
        # Nothing active — treat as no-op.
        PROGRESSION.unlink()
        print("Your save file had no active buddy; removed.")
        return 0

    buddies = dict(collection.get("buddies", {}))
    buddies.pop(active_id, None)

    if not buddies:
        PROGRESSION.unlink()
        print("Your buddy has been released. `/buddy hatch` to get a new one.")
        return 0

    # Promote another buddy to active (deterministic: first remaining).
    new_active = next(iter(buddies))
    collection["buddies"] = buddies
    collection["active_id"] = new_active
    tmp = PROGRESSION.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(collection, indent=2))
    os.replace(tmp, PROGRESSION)
    promoted = buddies[new_active]
    who = promoted.get("name") or promoted.get("species_name", "buddy")
    print(f"Released. {who} is now your active buddy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
