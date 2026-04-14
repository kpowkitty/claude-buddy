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

import time
update_state(
    last_event="pre_tool",
    current_tool=payload.get("tool_name"),
    session_id=payload.get("session_id"),
    watching_until=time.time() + 600,  # extend; cleared by Stop
)
