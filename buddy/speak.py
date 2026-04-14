#!/usr/bin/env python3
"""Decide whether buddy should speak, and if so, call Claude for a line.

Invoked in the background from hooks. Fails silently (never blocks session).

Flow:
  1. Read prefs.json — if quiet, exit 0.
  2. Load progression + state. No buddy, exit 0.
  3. Check rate-limit (last_speech_ts + species min_gap).
  4. Roll against event_weights[event] * base_rate.
  5. Build Haiku prompt: personality + event context + recent prompt/tool.
  6. Call API. Write result to state.json as speech + speech_ts.

Anything going wrong → exit silently. Buddy must never disrupt Claude Code.

Usage:
  python3 speak.py <event_type> [extra_context_json]

Requires: ANTHROPIC_API_KEY in env.
"""
from __future__ import annotations

import json
import pathlib
import random
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from state import BUDDY_DIR, STATE, PROGRESSION, read_json, write_atomic  # noqa: E402
from personality import for_species  # noqa: E402

PREFS = BUDDY_DIR / "prefs.json"
BASE_RATE = 0.35
MODEL = "haiku"  # alias for claude -p
TIMEOUT_SECONDS = 20


def _load_prefs():
    return read_json(PREFS, {"chatty": True})


def _should_speak(prog: dict, state: dict, event: str) -> bool:
    prefs = _load_prefs()
    if not prefs.get("chatty", True):
        return False
    pers = for_species(prog["species_id"])
    weights = pers["event_weights"]
    w = weights.get(event, 0)
    if w <= 0:
        return False
    last = state.get("last_speech_ts", 0)
    if time.time() - last < pers["min_gap_seconds"]:
        return False
    return random.random() < (BASE_RATE * w)


def _build_system(prog: dict, pers: dict) -> str:
    name = prog.get("name") or prog["species_name"]
    rarity = prog.get("rarity", "common")
    sig = prog.get("signature_skill", "")
    return (
        f"You are {name}, a {rarity} {prog['species_name']} — a tiny coding companion "
        f"watching over the user's terminal. Your signature skill is {sig}. "
        f"Voice: {pers['voice']}\n\n"
        "CRITICAL RULES:\n"
        "- Reply with ONE short line only, under 12 words.\n"
        "- No quotes, no prefixes, no 'Buddy says:'.\n"
        "- Never offer to write code or give technical advice — you're just a creature who chirps.\n"
        "- Stay in character. Stay brief. Be cute or grouchy per your voice."
    )


def _build_user(event: str, extra: dict) -> str:
    tool = extra.get("tool_name", "")
    event_desc = {
        "prompt": f"The user just submitted a new prompt.",
        "pre_tool": f"The assistant is about to use the {tool} tool.",
        "post_tool": f"The assistant just finished using the {tool} tool.",
        "tool_error": f"The {tool} tool just failed with an error.",
        "stop": "The assistant just finished its response.",
        "session_start": "A new Claude Code session has started. Greet the user briefly.",
    }.get(event, f"Event: {event}")
    return event_desc + "\n\nSay one short thing in your voice."


def _call_claude(system: str, user: str) -> str | None:
    """Shell out to `claude -p` so we use the user's Max auth, not a pay-per-token API key."""
    cli = shutil.which("claude")
    if not cli:
        return None
    import os
    env = os.environ.copy()
    env["BUDDY_INTERNAL"] = "1"  # hooks see this and skip
    try:
        result = subprocess.run(
            [
                cli, "-p", user,
                "--model", MODEL,
                "--system-prompt", system,
                "--output-format", "text",
                "--no-session-persistence",
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            env=env,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    text = (result.stdout or "").strip()
    # Strip surrounding quotes if present
    text = text.strip('"').strip("'").strip()
    return text or None


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    event = sys.argv[1]
    extra = {}
    if len(sys.argv) > 2:
        try:
            extra = json.loads(sys.argv[2])
        except json.JSONDecodeError:
            pass

    prog = read_json(PROGRESSION, None)
    if not prog:
        return 0
    state = read_json(STATE, {})
    if not _should_speak(prog, state, event):
        return 0

    pers = for_species(prog["species_id"])
    line = _call_claude(_build_system(prog, pers), _build_user(event, extra))
    if not line:
        return 0

    state["speech"] = line
    state["speech_ts"] = time.time()
    state["last_speech_ts"] = time.time()
    write_atomic(STATE, state)
    return 0


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # never surface errors to the parent hook
