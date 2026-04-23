"""Opt-in debug log for TUI diagnostics.

Writes to /tmp/spike.log only when BUDDY_DEBUG=1 is set in the env.
Keeps tracing machinery in the tree (SPAWN/RESIZE/KEY etc.) without
paying the I/O cost or filling disks during normal use.

Usage:
    from debug_log import log
    log(f"KEY key={event.key!r}")

Enable:
    BUDDY_DEBUG=1 /path/to/claude-buddy
"""
from __future__ import annotations

import os
import time

_ENABLED = os.environ.get("BUDDY_DEBUG") == "1"
_PATH = "/tmp/spike.log"


def log(line: str) -> None:
    """Append a timestamped line to the debug log. No-op unless enabled."""
    if not _ENABLED:
        return
    try:
        with open(_PATH, "a") as f:
            f.write(f"{time.time():.3f} {line}\n")
    except Exception:
        pass
