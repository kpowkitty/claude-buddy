#!/usr/bin/env python3
"""Release the current buddy. Usage: python3 forget.py --confirm"""
from __future__ import annotations

import pathlib
import sys

PROGRESSION = pathlib.Path.home() / ".claude" / "buddy" / "progression.json"


def main() -> int:
    if "--confirm" not in sys.argv:
        print("This will permanently release your current buddy.")
        print("Re-run: `/buddy forget --confirm`")
        return 1
    if not PROGRESSION.exists():
        print("No buddy to release.")
        return 0
    PROGRESSION.unlink()
    print("Your buddy has been released. `/buddy hatch` to get a new one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
