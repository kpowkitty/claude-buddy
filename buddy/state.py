"""Shared state read/write helpers for buddy hooks and renderer."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

# BUDDY_STATE_DIR env var lets you point every script at a throwaway
# directory (see buddy/tests/) so simulation test runs don't touch your
# real save files. Leave unset for normal operation.
_DEFAULT_BUDDY_DIR = pathlib.Path.home() / ".claude" / "buddy"
BUDDY_DIR = pathlib.Path(os.environ["BUDDY_STATE_DIR"]).expanduser() if os.environ.get("BUDDY_STATE_DIR") else _DEFAULT_BUDDY_DIR
STATE = BUDDY_DIR / "state.json"
PROGRESSION = BUDDY_DIR / "progression.json"

IS_TEST_MODE = bool(os.environ.get("BUDDY_STATE_DIR"))

# Make `collection` importable from any of our scripts whether they were
# invoked from this directory or elsewhere.
_HERE = pathlib.Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


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


def push_event(event: dict) -> None:
    """Append `event` to state.json['pending_events'] atomically.

    The Textual app's chirp_loop consumes these. Hooks enqueue; the loop
    dequeues one event per IDLE tick.
    """
    s = read_json(STATE, {})
    queue = list(s.get("pending_events") or [])
    queue.append(dict(event))
    s["pending_events"] = queue
    write_atomic(STATE, s)


def read_collection() -> dict:
    """Read progression.json and migrate old single-buddy shape on the fly.

    Always returns a dict in the collection shape. If the file doesn't exist
    or is empty, returns an empty collection. Added for the gacha-collection
    refactor; existing single-buddy callers still use read_json(PROGRESSION).
    Step 2 migrates the callers; until then this lives alongside.
    """
    from collection import migrate  # local import to avoid cycle at module load
    raw = read_json(PROGRESSION, {})
    return migrate(raw or {})


def write_collection(collection: dict) -> None:
    """Persist a collection-shaped dict to progression.json."""
    write_atomic(PROGRESSION, collection)


def bump_progression(**deltas) -> dict:
    """Add deltas to counters on the ACTIVE buddy. Returns the new collection.

    Pre-collection callers used this to increment per-buddy fields like
    `pets_received`. Semantically unchanged: deltas land on the active
    buddy's entry, not on collection-level counters.
    """
    from collection import active_buddy, migrate  # local import avoids cycle

    raw = read_json(PROGRESSION, None)
    if raw is None:
        return {}
    collection = migrate(raw)
    active_id = collection.get("active_id")
    buddy = active_buddy(collection)
    if not active_id or buddy is None:
        return collection
    buddy = dict(buddy)
    for key, delta in deltas.items():
        buddy[key] = buddy.get(key, 0) + delta
    collection["buddies"] = dict(collection.get("buddies", {}))
    collection["buddies"][active_id] = buddy
    write_atomic(PROGRESSION, collection)
    return collection


def derive_mood(state: dict) -> str:
    """Compute mood from state + timing.

    Uses explicit deadline timestamps (`watching_until`, `petted_until`) so
    short-lived moods persist across renders rather than flickering on the
    single tick a hook fires.

    Returns one of: idle | attentive | watching | sleeping | petted.
    (celebrating is reserved for rare events, not routine stops.)
    """
    now = time.time()
    petted_until = state.get("petted_until", 0)
    if now < petted_until:
        return "petted"
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
