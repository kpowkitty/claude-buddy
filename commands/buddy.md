---
description: Your coding companion — hatch one, check on them, name them
argument-hint: "[hatch --tokens | hatch --shards | switch <name> | name <name> | forget --confirm | quiet | chatty]"
---

You are running the `/buddy` command. The user's arguments are: $ARGUMENTS

Dispatch based on the first argument:

- If `$ARGUMENTS` is empty, run: `python3 ${CLAUDE_PLUGIN_ROOT}/buddy/show.py`
- If it starts with `hatch`, run: `python3 ${CLAUDE_PLUGIN_ROOT}/buddy/hatch.py <rest of args>` (forward everything after `hatch` — `--tokens`, `--shards`, or nothing to get the usage hint)
- If it starts with `switch`, run: `python3 ${CLAUDE_PLUGIN_ROOT}/buddy/switch.py <rest of args>`
- If it starts with `name`, run: `python3 ${CLAUDE_PLUGIN_ROOT}/buddy/name.py <rest of args>`
- If it starts with `forget`, run: `python3 ${CLAUDE_PLUGIN_ROOT}/buddy/forget.py <rest of args>`
- If it is `quiet` or `chatty`, run: `python3 ${CLAUDE_PLUGIN_ROOT}/buddy/quiet.py <that word>`

The Bash tool result already displays the script's output to the user with proper ANSI colors. Do NOT re-print it in your text response — that would show raw escape codes and duplicate the output. Your text response should be empty, or at most a single short sentence if there's something useful to add. Usually just say nothing.
