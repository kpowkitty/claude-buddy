# claude-buddy

A gacha-rolled ASCII coding companion for [Claude Code](https://claude.com/claude-code). Hatch one, name them, and they'll live in the top-right corner of your terminal next to Claude, watching you code and occasionally piping up with personality-driven remarks.

```
 ╭──────────────────────╮
 │     tests don't      │
 │    lie, but your     │
 │  assumptions do 🦊   │
 ╰──────────────────────╯
            ▼
       /\   /\
      (  \_/  )  /
       \ ^.^ /   \
        > v <     |
       /     \ ~~/
      (_______)

       ★ quine ★
         lvl 3
     ████████░░░░░░░░
    with you 2d 4h
```

## What it does

- **Gacha hatch**: `/buddy hatch --tokens` rolls a rarity (common 60% / uncommon 25% / rare 10% / epic 4% / legendary 1%) and a species within that tier. 11 species total.
- **Collection economy**: hatch tokens unlock on an escalating schedule based on your global level (sum of every buddy's pet level). Token 1 at 5 levels, token 2 at 15, token 3 at 30, token 4 at 50 — each token costs 5 more pet-levels than the last. Rolling a species you already own on `--tokens` burns the token but grants a duplicate shard; 5 shards can be spent via `--shards` for a guaranteed new species.
- **Skills**: every buddy rolls 8 skill stats (wisdom, debugging, refactoring, etc.). Each species has a baseline range and a signature skill that rolls much higher.
- **Embedded TUI**: `claude-buddy` launches Claude Code inside a Textual app, with your buddy animated as a floating overlay in the top-right reacting to what you're doing.
- **L-shape reflow**: Claude's text wraps around the pet's reserved rectangle so nothing lands under the overlay. Once Claude's conversation fills past the pet zone, it gets the full terminal width back.
- **Hooks**: watches `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SessionStart` to shift mood (idle / attentive / watching / sleeping / petted / celebrating).
- **Personality-driven speech**: your buddy can occasionally pipe up in character via Claude — wise Owlet quotes proverbs, Dragonling snarls at errors, Moonwyrm speaks in cosmic riddles. Uses your existing Claude Code auth (no separate API key).
- **Pet your buddy**: `F1` closes its eyes into a smile, triggers a `prrr` speech bubble, and ticks up its `pets_received` counter.
- **Talk to your buddy directly**: prefix a line with `~{name}` (e.g. `~quine what color is the sky`) to have your buddy reply instead of Claude.
- **Wakes on interaction**: a sleeping buddy (idle >120s) wakes back up the moment you prompt Claude or talk to it directly.

## Install

Requires Python 3.10+ and the Claude Code CLI (`claude`) on your PATH.

```bash
git clone https://github.com/kpowkitty/claude-buddy.git
cd claude-buddy
./install.sh
```

The installer:

- creates a venv at `buddy/tui/.venv` and installs runtime deps,
- copies hook scripts to `~/.claude/buddy/` and merges hook entries into `~/.claude/settings.json`,
- symlinks `bin/claude-buddy` and `bin/claude-buddy-hatch` into `~/.local/bin/` so you can launch from any directory,
- offers to hatch your first buddy right away.

If `~/.local/bin` isn't on your PATH, the installer prints a one-liner to add it.

After installing, restart Claude Code so the hooks take effect — Claude reads `~/.claude/settings.json` once at startup, so an already-running session won't see the new hooks. If you skipped the hatch prompt, roll your first buddy with `claude-buddy-hatch --tokens` (or `/buddy hatch --tokens` inside Claude).

## Usage

Launch the TUI from any terminal:

```bash
claude-buddy
```

Roll a new buddy without opening Claude:

```bash
claude-buddy-hatch --tokens   # spend a hatch token (dupes burn it and grant a shard)
claude-buddy-hatch --shards   # spend 5 shards for a guaranteed new species
```

Claude Code runs full-width; your buddy floats in a reserved rectangle in the top-right corner.

### Keybindings (TUI)

All app-level hotkeys are function keys so they never collide with Claude's own bindings.

| Key | Action |
|---|---|
| `Ctrl-Q` | Quit the app |
| `F1` | Pet the active buddy (2-second `prrr` reaction) |
| `F2` | Open the gacha collection menu |
| `F3` | Toggle the skill grid |
| `F4` | Toggle the buddy panel on/off |
| `F5` | Refresh — force Claude to redraw if the view gets corrupted |
| Scroll wheel | Scroll through the Claude pane's history (pauses the live feed) |
| `Shift-PageUp` / `Shift-PageDown` | Same, via keyboard |
| `Shift-End` | Snap back to the live tail |
| Any keystroke | Resumes live tail if you're scrolled back |

### Gacha menu (F2)

Opens a modal showing every species you own, grouped by rarity. Arrow keys (or `j`/`k`) navigate slots; Enter switches to the highlighted buddy; `q` or Escape closes. Your active buddy is marked with a star.

### Talk to your buddy

Prefix any line with `~{name}` to have the buddy reply instead of Claude:

```
~quine what do you think about this bug?
```

Claude never sees the message; your buddy's reply lands in the speech bubble.

### Claude Code slash commands

All `/buddy` commands work inside Claude (whether launched via `claude-buddy` or plain `claude`):

- `/buddy hatch --tokens` — spend a hatch token (dupes grant a shard)
- `/buddy hatch --shards` — spend 5 shards for a guaranteed new species
- `/buddy` — show the active buddy's card (art, skills, age)
- `/buddy switch <name>` — make another buddy active (matches name or species)
- `/buddy name <name>` — rename the active buddy
- `/buddy quiet` / `/buddy chatty` — toggle whether they speak
- `/buddy forget --confirm` — release them so you can hatch a new one

## How it works

```
┌──────────────────────────────────────────────────────────────────┐
│  claude-buddy TUI (Textual)                                      │
│                                                                  │
│  ┌──────────────────────────────┐  ┌────────────────────────┐    │
│  │  Claude Code (in a PTY,      │  │  Habitat overlay       │    │
│  │  rendered via pyte)          │  │  (floats top-right):   │    │
│  │                              │  │    speech bubble       │    │
│  │  Claude's text wraps around  │  │    sprite              │    │
│  │  the pet's reserved rect ────┼▶│    name + XP + time    │    │
│  │  (L-shape reflow)            │  │    skills (toggle)     │    │
│  │                              │  │                        │    │
│  │  /buddy commands             │  │  reads state.json      │    │
│  │  + 5 lifecycle hooks ────────┼▶│  animates at 10 fps    │    │
│  └──────────────────────────────┘  └────────────────────────┘    │
│                                                                  │
│         writes to ~/.claude/buddy/state.json                     │
└──────────────────────────────────────────────────────────────────┘
```

**Hook pipeline.** Claude Code fires 5 lifecycle events. Each hook script atomically writes `state.json` with the current mood + tool + timestamp. The Textual app polls that file to drive the sprite animation, mood, and optional speech bubble. Speech is produced by shelling out to `claude -p` via `speak.py` — same auth, no separate API key.

**L-shape reflow.** The pet reserves a 24×18 rectangle in the top-right (chat bubble + sprite + name + XP + time). Inside those rows, Claude's text is wrapped at `cols - 24` by a custom `pyte.HistoryScreen` subclass (`lreflow.py`). Once Claude's content extends below the pet zone, the widget tells Claude it has the full terminal width and reflows the visible content via Ctrl+L. On resize, the pane auto-refreshes so no stale pixels linger.

**Animation.** Sprites animate on independent cycles: a steady 1-second tail wag for species with a `tail_b` alternate frame, layered with a ~10-second blink. Sleeping buddies stop wagging entirely.

## File structure

```
claude-buddy/
├── bin/
│   ├── claude-buddy           # launcher shim (runs buddy/tui/cli.py)
│   └── claude-buddy-hatch     # CLI hatch wrapper (runs buddy/hatch.py)
├── buddy/
│   ├── buddy.py               # standalone side-panel (pre-TUI CLI viewer)
│   ├── collection.py          # gacha collection schema + migrations
│   ├── forget.py              # /buddy forget implementation
│   ├── hatch.py               # gacha roll logic (rarity + species draw)
│   ├── messages.py            # static buddy quips / canned lines
│   ├── name.py                # /buddy name implementation
│   ├── personality.py         # per-species voice, event weights, prompt prefix
│   ├── quiet.py               # /buddy quiet/chatty toggle
│   ├── show.py                # /buddy card renderer
│   ├── speak.py               # shells out to `claude -p` for personality speech
│   ├── species.py             # 11 species: art, rarity, skill ranges, signature
│   ├── sprites.py             # mood/frame generation (blink, wag, overlays)
│   ├── state.py               # state.json read/write + derive_mood
│   ├── switch.py              # /buddy switch implementation
│   ├── hooks/                 # Claude Code lifecycle hooks
│   │   ├── on_prompt.py       # UserPromptSubmit → mood 'attentive'
│   │   ├── on_pre_tool.py     # PreToolUse      → mood 'watching'
│   │   ├── on_post_tool.py    # PostToolUse     → XP + event log
│   │   ├── on_session.py      # SessionStart    → bump time_with_buddy
│   │   └── on_stop.py         # Stop            → settle to 'idle'
│   ├── tests/                 # hand-play simulation harness (read tests/README.md)
│   │   ├── env/               # per-scenario BUDDY_STATE_DIR fixtures
│   │   ├── fixtures/          # canned state.json + progression.json snapshots
│   │   └── run                # sourceable script (bash or zsh)
│   └── tui/
│       ├── app.py             # BuddyApp — composes PtyTerminal + Habitat
│       ├── pty_terminal.py    # Widget that runs Claude in a pyte-backed PTY
│       ├── lreflow.py         # pyte.HistoryScreen subclass enforcing the
│       │                      #   row-dependent right edge for the pet overlay
│       ├── habitat.py         # Sprite, NamePanel, XPBar, SkillGrid, Bubble,
│       │                      #   TimeWithBuddy, SkillGrid, Habitat container
│       ├── gacha_menu.py      # F2 modal — rarity-grouped collection browser
│       ├── state_adapter.py   # reads state.json → BuddyView snapshot
│       ├── input_map.py       # keyboard event → child-pty bytes
│       ├── chirp_loop.py      # picks speech-bubble moments (rate-limited)
│       ├── chirp_loop_wiring.py  # wires chirp_loop into the app's polling
│       ├── cli.py             # launcher — parses args, sets up env, runs app
│       └── tests/             # pytest suite — 199 tests over the TUI + logic
├── commands/
│   └── buddy.md               # Claude slash-command spec for /buddy
├── hooks/
│   └── hooks.json             # hook registration entries merged at install
├── install.sh
├── requirements.txt
└── README.md
```

## Development

### Running tests

```bash
buddy/tui/.venv/bin/pytest buddy/tui/tests/
```

All correctness checks (render logic, input routing, state schema, reflow contracts, scrollback). 199 tests as of this writing.

### Hand-play simulation

`buddy/tests/run` is a sourceable shell script that sets `BUDDY_STATE_DIR` to a throwaway directory preloaded with fixture state, then launches the TUI. Useful for trying the UI against specific mood/progression scenarios without touching your real buddy. See `buddy/tests/README.md`.

### Debug flags

- `BUDDY_LREFLOW=0` — disable the L-shape reflow (falls back to plain `pyte.HistoryScreen`). The pet overlay will cover live Claude text; useful for isolating reflow bugs.
- `BUDDY_STATE_DIR=/path/to/dir` — redirect reads and writes of state/progression away from `~/.claude/buddy/`. The TUI shows a red **TEST MODE** banner so you can't forget.

## Contributing

PRs welcome! Especially for:

- **New species** — add to `buddy/species.py` (art, skill ranges, signature skill) and `buddy/personality.py` (voice, event weights). Optionally include a `tail_b` dict for a wag animation.
- **Better animations** — tweak `buddy/sprites.py` for mood-specific frames.
- **New moods or hook reactions** — extend the mood logic in `buddy/state.py` and sprite handling in `buddy/sprites.py`.
- **Layout / rendering fixes** — the PTY + L-reflow composition in `buddy/tui/` has known rough edges in very narrow terminals (<80 cols).

Open an issue if you have ideas.

## License

BSD 3-Clause. See [LICENSE](LICENSE).
