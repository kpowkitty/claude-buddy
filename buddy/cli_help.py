"""Shared CLI help output.

Every buddy command routes failure (and --help) through `print_help()` so
the user always sees their current state + every available command without
having to go dig through docs.

Pure function of the collection it's handed, plus the ANSI color toggles
from hatch.py — keeps output consistent across scripts.
"""
from __future__ import annotations

import sys
from typing import Optional

from collection import (
    LEVELS_PER_TOKEN_STEP,
    SHARDS_PER_REDEEM,
    active_buddy,
    all_buddies,
    global_level,
    hatches_available,
    shards,
    tokens_earned,
)

# Import colors from hatch; if hatch hasn't been imported yet that's fine —
# they're just strings. Duplicating them here avoids a circular import when
# hatch.py imports this module.
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_RED_BG = "\033[41m"  # bright-red background for TEST MODE banner
_WHITE_BOLD = "\033[1;37m"


def _status_block(collection: dict) -> list[str]:
    """Report active buddy + economy counters."""
    lines: list[str] = []
    buddy = active_buddy(collection)
    if buddy:
        name = buddy.get("name") or buddy.get("species_name") or "buddy"
        level = int(buddy.get("level", 1))
        lines.append(
            f"  {_BOLD}{name}{_RESET} "
            f"{_DIM}({buddy.get('species_name', '?')}, {buddy.get('rarity', '?')}, lvl {level}){_RESET}"
        )
    else:
        lines.append(f"  {_DIM}(no active buddy yet){_RESET}")

    n_buddies = len(all_buddies(collection))
    gl = global_level(collection)
    available = hatches_available(collection)
    sh = shards(collection)

    lines.append(
        f"  Collection: {n_buddies} buddy(s)  ·  "
        f"global lvl {_BOLD}{gl}{_RESET}  ·  "
        f"tokens {tokens_earned(collection)}  ·  "
        f"shards {sh}"
    )

    if available > 0:
        lines.append(
            f"  {_CYAN}{available} hatch(es) ready — run: claude-buddy-hatch --tokens{_RESET}"
        )
    else:
        # Explain how far from the next token. The (K+1)-th token's
        # cumulative cost is STEP × (K+1)(K+2)/2 total pet levels.
        k = tokens_earned(collection)
        next_token_at = LEVELS_PER_TOKEN_STEP * (k + 1) * (k + 2) // 2
        pet_levels_needed = max(0, next_token_at - gl)
        lines.append(
            f"  {_DIM}No hatches available. Next token in ~{pet_levels_needed} more pet-level(s).{_RESET}"
        )
        lines.append(f"  {_DIM}Earn shards by rolling duplicates.{_RESET}")

    if sh >= SHARDS_PER_REDEEM:
        lines.append(
            f"  {_YELLOW}{sh} shard(s) — hatch available! Run: claude-buddy-hatch --shards{_RESET}"
        )

    return lines


def _command_block() -> list[str]:
    """Enumerate every command so the user has one place to scan."""
    return [
        f"  {_BOLD}Commands (run from any terminal):{_RESET}",
        f"    claude-buddy                 launch the TUI (Claude + buddy)",
        f"    claude-buddy-hatch --tokens  spend a hatch token",
        f"    claude-buddy-hatch --shards  spend 5 shards for a guaranteed new species",
        f"    claude-buddy-hatch --help    this message",
        "",
        f"  {_BOLD}Inside Claude Code:{_RESET}",
        f"    /buddy                       show your active buddy's card",
        f"    /buddy hatch --tokens        spend a hatch token",
        f"    /buddy hatch --shards        spend shards",
        f"    /buddy switch <name>         make another buddy active",
        f"    /buddy name <name>           name your active buddy",
        f"    /buddy forget --confirm      release your active buddy",
        f"    /buddy quiet | /buddy chatty toggle whether buddy speaks",
        "",
        f"  {_BOLD}In the TUI:{_RESET}",
        f"    F1   pet your buddy",
        f"    F2   open the gacha collection menu",
        f"    F3   toggle the skills panel",
        f"    F4   toggle the buddy panel",
        f"    ~{{name}} <msg>   talk to your buddy (e.g. ~quine hi)",
    ]


def print_test_mode_banner() -> None:
    """Loud banner shown whenever BUDDY_STATE_DIR is set. Prints to stdout.

    Called at the top of every CLI script's output, and by print_help()
    for any error path that routes through it.
    """
    import os
    state_dir = os.environ.get("BUDDY_STATE_DIR")
    if not state_dir:
        return
    # Size the top/bottom rules to exactly match the content line so the
    # box doesn't appear ragged on wide/narrow state-dir paths.
    label = f"  ⚠  TEST MODE  ·  state dir: {state_dir}  "
    # The emoji is 2 columns wide in most terminals; len() sees one codepoint.
    # Add 1 to compensate so the rules visually line up.
    bar = "━" * (len(label) + 1)
    print(f"{_RED_BG}{_WHITE_BOLD}{bar}{_RESET}")
    print(f"{_RED_BG}{_WHITE_BOLD}{label}{_RESET}")
    print(f"{_RED_BG}{_WHITE_BOLD}{bar}{_RESET}")


def print_help(collection: Optional[dict] = None, *, header: Optional[str] = None) -> None:
    """Print status + full command reference to stdout.

    `header` lets callers prefix a context-specific reason (e.g. "No hatches
    available yet."). Collection is optional — if None, the status block
    is skipped (useful before the save file exists).

    Does NOT print the TEST MODE banner — main() should call that once at
    the top of script execution so error paths don't double-print.
    """
    if header:
        print(header)
        print()
    if collection is not None:
        print(f"  {_BOLD}Status{_RESET}")
        for line in _status_block(collection):
            print(line)
        print()
    for line in _command_block():
        print(line)
    print()
