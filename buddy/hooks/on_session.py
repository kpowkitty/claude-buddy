#!/usr/bin/env python3
import json
import os
import pathlib
import sys

if os.environ.get("BUDDY_INTERNAL"):
    sys.exit(0)

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from state import update_state  # noqa: E402

try:
    payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
except json.JSONDecodeError:
    payload = {}

update_state(
    last_event="session_start",
    current_tool=None,
    session_id=payload.get("session_id"),
)

import subprocess
subprocess.Popen(
    ["python3", str(pathlib.Path(__file__).parent.parent / "speak.py"), "session_start"],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    start_new_session=True,
)
