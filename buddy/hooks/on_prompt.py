#!/usr/bin/env python3
"""UserPromptSubmit hook.

Stashes the user's prompt text into state.json so the next Stop event can
bundle it into a pending chirp event. No direct chirp spawn — the Textual
app's chirp_loop owns chirp generation.
"""
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
    last_event="prompt",
    current_tool=None,
    session_id=payload.get("session_id"),
    watching_until=time.time() + 600,  # stay watching until Stop clears it
    last_user_prompt=payload.get("prompt", ""),
)
bump_progression(total_prompts=1)
