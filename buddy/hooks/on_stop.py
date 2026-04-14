#!/usr/bin/env python3
"""Stop hook.

Enqueues a chirp event into state.json carrying both the user's prompt (set
by on_prompt.py) and Claude's final response. The Textual app's chirp_loop
picks it up on its next IDLE tick, rolls to speak, and (maybe) drafts a
context-aware chirp.
"""
import json
import os
import pathlib
import sys
import time

if os.environ.get("BUDDY_INTERNAL"):
    sys.exit(0)

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from state import read_json, update_state, push_event, STATE  # noqa: E402

try:
    payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
except json.JSONDecodeError:
    payload = {}

update_state(
    last_event="stop",
    current_tool=None,
    session_id=payload.get("session_id"),
    watching_until=0,  # response done — stop watching
)

state_before = read_json(STATE, {})
push_event({
    "kind": "stop",
    "ts": time.time(),
    "user_prompt": state_before.get("last_user_prompt", "") or "",
    "assistant_response": payload.get("last_assistant_message", "") or "",
})
