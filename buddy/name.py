#!/usr/bin/env python3
"""Set your buddy's name. Usage: python3 name.py <name...>"""
from __future__ import annotations

import json
import os
import pathlib
import sys

PROGRESSION = pathlib.Path.home() / ".claude" / "buddy" / "progression.json"


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: /buddy name <name>")
        return 1
    new_name = " ".join(sys.argv[1:]).strip()
    if not new_name:
        print("Name can't be empty.")
        return 1
    if len(new_name) > 40:
        print("Name too long (max 40 chars).")
        return 1
    if not PROGRESSION.exists():
        print("You don't have a buddy yet. Run `/buddy hatch` first.")
        return 1
    data = json.loads(PROGRESSION.read_text())
    data["name"] = new_name
    tmp = PROGRESSION.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, PROGRESSION)
    print(f"Named your {data['species_name']}: {new_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
