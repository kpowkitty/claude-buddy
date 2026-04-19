#!/usr/bin/env python3
"""Toggle buddy chattiness. Usage: python3 quiet.py <quiet|chatty>"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cli_help import print_help, print_test_mode_banner  # noqa: E402
from collection import migrate  # noqa: E402
from state import BUDDY_DIR, PROGRESSION, read_json, write_atomic  # noqa: E402

PREFS = BUDDY_DIR / "prefs.json"


def _load_collection() -> dict | None:
    raw = read_json(PROGRESSION, None)
    if raw is None:
        return None
    return migrate(raw)


def main() -> int:
    print_test_mode_banner()
    if set(sys.argv[1:]) & {"--help", "-h"}:
        print_help(_load_collection(), header="Usage: /buddy quiet | /buddy chatty")
        return 0
    if len(sys.argv) < 2 or sys.argv[1] not in ("quiet", "chatty"):
        prefs = read_json(PREFS, {"chatty": True})
        state = "chatty" if prefs.get("chatty", True) else "quiet"
        print_help(
            _load_collection(),
            header=f"Buddy is currently {state}. Usage: /buddy quiet | /buddy chatty",
        )
        return 0
    chatty = sys.argv[1] == "chatty"
    write_atomic(PREFS, {"chatty": chatty})
    if chatty:
        print("Buddy is chatty. They may speak up on events.")
    else:
        print("Buddy is quiet. They won't say anything.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
