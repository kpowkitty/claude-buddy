#!/usr/bin/env python3
import json
import os
import pathlib
import sys

if os.environ.get("BUDDY_INTERNAL"):
    sys.exit(0)

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from state import update_state, bump_progression  # noqa: E402

try:
    payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
except json.JSONDecodeError:
    payload = {}

import time
update_state(
    last_event="post_tool",
    current_tool=payload.get("tool_name"),
    session_id=payload.get("session_id"),
    watching_until=time.time() + 600,  # keep watching until Stop
)
bump_progression(total_tools=1)

# Detect tool error via payload (best-effort; field may vary)
tool_response = payload.get("tool_response") or {}
is_error = bool(tool_response.get("is_error")) if isinstance(tool_response, dict) else False
event_type = "tool_error" if is_error else "post_tool"

import json as _json, subprocess
subprocess.Popen(
    ["python3", str(pathlib.Path(__file__).parent.parent / "speak.py"),
     event_type, _json.dumps({"tool_name": payload.get("tool_name", "")})],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    start_new_session=True,
)
