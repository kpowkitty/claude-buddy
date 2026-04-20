# Simulation tests

Throwaway environments for hand-testing the CLI and TUI against canned
progression states without touching your real save file at
`~/.claude/buddy/`.

This is the "try the collection menu with five shards" or "see what the
UI does with two buddies" kind of testing — **not** automated correctness
checks. For those, see `buddy/tui/tests/README.md`.

## Usage

```bash
# toggle on with the default empty fixture
source claude-buddy-tests

# or pick a specific fixture
source claude-buddy-tests two-buddies
source claude-buddy-tests ready-to-hatch
source claude-buddy-tests five-shards

# while on, every claude-buddy / claude-buddy-hatch / TUI read+writes
# from buddy/tests/env/ instead of ~/.claude/buddy/. A loud red banner
# appears in CLI output and at the top of the TUI.

claude-buddy-hatch --tokens
claude-buddy

# toggle off: sources a second time with no arg, wipes buddy/tests/env
source claude-buddy-tests
```

The script **must be sourced**, not executed — it exports `BUDDY_STATE_DIR`
into your parent shell. Running it as `claude-buddy-tests` will refuse and
print a reminder.

## Fixtures

- **empty** — no buddies, no shards. Exercises the starter-gift path.
- **two-buddies** — slime + ember. Good for testing `/buddy switch`.
- **ready-to-hatch** — one level-40 slime. One token available, no shards.
- **five-shards** — one buddy and 5 shards ready to redeem.
- **full-roster** — every species unlocked. For reviewing sprites / animations across the whole roster.

Add new fixtures by dropping a `<name>.json` into `fixtures/`. They're
committed to the repo (templates), but the `env/` directory the toggle
script seeds from them is gitignored.
