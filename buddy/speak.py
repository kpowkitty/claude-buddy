#!/usr/bin/env python3
"""Drafter for buddy chirps — used two ways:

1. **Library**: imported by the Textual app's chirp_loop (via `should_speak`,
   `build_system`, `build_user`, `call_claude`). Each piece is a small pure
   function the state machine composes.

2. **Script**: `python3 speak.py <event> [extra_json]` runs the whole flow
   (roll → draft → write state.json). Retained for dev tooling and legacy
   hooks that haven't been migrated. Failing silently never disrupts Claude
   Code. Going forward, the Textual app owns chirp generation end-to-end
   via chirp_loop; this main() is a compatibility shim.
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
from collection import active_buddy, migrate  # noqa: E402
from personality import for_species  # noqa: E402


def _read_active_prog() -> dict | None:
    """Load progression.json, migrate if needed, return the active buddy
    dict (flat shape, same as pre-collection callers expected)."""
    raw = read_json(PROGRESSION, None)
    if raw is None:
        return None
    return active_buddy(migrate(raw))

PREFS = BUDDY_DIR / "prefs.json"
BASE_RATE = 0.35
MODEL = "haiku"  # alias for claude -p
TIMEOUT_SECONDS = 20


def _load_prefs():
    return read_json(PREFS, {"chatty": True})


def should_speak(prog: dict, state: dict, event: str) -> bool:
    """Roll prob + cooldown to decide whether buddy speaks on this event.

    Pure function of its inputs. Reused by chirp_loop.
    """
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


# Back-compat alias — old callers may import _should_speak.
_should_speak = should_speak


def build_system(prog: dict, pers: dict) -> str:
    name = prog.get("name") or prog["species_name"]
    rarity = prog.get("rarity", "common")
    sig = prog.get("signature_skill", "")
    examples = pers.get("examples") or []
    examples_block = ""
    if examples:
        joined = "\n".join(f"  - {ex}" for ex in examples)
        examples_block = (
            f"\n\nExamples of how you speak (match this tone and brevity — don't copy verbatim):\n{joined}"
        )
    return (
        f"You are {name}, a {rarity} {prog['species_name']} — a tiny companion "
        f"living in the user's terminal. Your signature skill is {sig}.\n\n"
        f"Voice:\n{pers['voice']}"
        f"{examples_block}\n\n"
        "RULES:\n"
        "- Reply with ONE short line only, under 15 words.\n"
        "- No quotes, no prefixes, no 'Buddy says:'.\n"
        "- Stay in your voice. Your personality decides how you respond —\n"
        "  whether you answer, deflect, joke, hint, or ignore is up to your character.\n"
        "- Don't be annoying."
    )


def build_user(kind: str, text: str) -> str:
    """Single user-message template. `kind` is short human prose describing
    what to respond to (e.g. 'the user's question', 'a user prompt',
    'a claude response', 'a session_start event'). `text` is the content.

    The system prompt tells the buddy who it is; this tells it what to react
    to. Voice decides whether it engages with the content or chirps around it.
    """
    text = (text or "").strip()
    kind = (kind or "an event").strip() or "an event"
    if text:
        return f"Respond to {kind}:\n  \"{text}\""
    return f"Respond to {kind}."


# Back-compat aliases.
_build_user = build_user


def call_claude(system: str, user: str) -> str | None:
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


def _script_event_to_prompt(event: str, extra: dict) -> tuple[str, str]:
    """Map the legacy hook-script event name to (kind, text) for build_user.

    Only used by the script entry point (main()); the Textual app composes
    these directly.
    """
    tool = extra.get("tool_name", "")
    if event == "prompt":
        return ("a user prompt", "")
    if event == "pre_tool":
        return ("a pre-tool event", f"about to use {tool}" if tool else "")
    if event == "post_tool":
        return ("a post-tool event", f"finished using {tool}" if tool else "")
    if event == "tool_error":
        return ("a tool error", f"{tool} failed" if tool else "")
    if event == "stop":
        return ("a claude stop event", "")
    if event == "session_start":
        return ("a session_start event (greet the user)", "")
    return (f"a {event} event", "")


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

    prog = _read_active_prog()
    if not prog:
        return 0
    state = read_json(STATE, {})
    if not should_speak(prog, state, event):
        return 0

    pers = for_species(prog["species_id"])
    kind, text = _script_event_to_prompt(event, extra)
    line = call_claude(build_system(prog, pers), build_user(kind, text))
    if not line:
        return 0

    state["speech"] = line
    state["speech_ts"] = time.time()
    state["last_speech_ts"] = time.time()
    write_atomic(STATE, state)
    return 0


# Back-compat aliases for the underscore-prefixed names.
_build_system = build_system
_call_claude = call_claude


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # never surface errors to the parent hook
