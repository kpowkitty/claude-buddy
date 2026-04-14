"""Shared state read/write helpers for buddy hooks and renderer."""
from __future__ import annotations

import json
import os
import pathlib
import time

BUDDY_DIR = pathlib.Path.home() / ".claude" / "buddy"
STATE = BUDDY_DIR / "state.json"
PROGRESSION = BUDDY_DIR / "progression.json"


def read_json(path: pathlib.Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default if default is not None else {}


def write_atomic(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def update_state(**fields) -> None:
    """Update state.json with given fields; always stamps last_event_ts."""
    s = read_json(STATE, {})
    s.update(fields)
    s["last_event_ts"] = time.time()
    write_atomic(STATE, s)


def bump_progression(**deltas) -> dict:
    """Add deltas to counters in progression.json. Returns new progression."""
    p = read_json(PROGRESSION, None)
    if p is None:
        return {}
    for key, delta in deltas.items():
        p[key] = p.get(key, 0) + delta
    write_atomic(PROGRESSION, p)
    return p


def derive_mood(state: dict) -> str:
    """Compute mood from state + timing.

    Uses an explicit `watching_until` timestamp so buddy stays in `watching`
    for the whole span from first pre_tool to response stop, not just the
    moment a hook fires.

    Returns one of: idle | attentive | watching | sleeping.
    (celebrating is reserved for rare events, not routine stops.)
    """
    now = time.time()
    watching_until = state.get("watching_until", 0)
    if now < watching_until:
        return "watching"

    last_event = state.get("last_event")
    last_ts = state.get("last_event_ts", 0)
    age = now - last_ts

    if age > 120:
        return "sleeping"
    if last_event == "prompt" and age < 3:
        return "attentive"
    return "idle"
