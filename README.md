# claude-buddy

A gacha-rolled ASCII coding companion for [Claude Code](https://claude.com/claude-code). Hatch one, name them, and they'll live in a side panel next to Claude, watching you code and occasionally piping up with personality-driven remarks.

```
     /\   /\
    (  \_/  )  /
     \ ^.^ /   \
      > v <     |
     /     \ ~~/
    (_______)

   ★ quine · Kitsune · epic ★
```

## What it does

- **Gacha hatch**: `/buddy hatch` rolls a rarity (common 60% / uncommon 25% / rare 10% / epic 4% / legendary 1%) and a species within that tier. 11 species total.
- **Skills**: every buddy rolls 8 skill stats (wisdom, debugging, refactoring, etc.). Each species has a baseline range and a signature skill that rolls much higher.
- **Embedded TUI**: `claude-buddy` launches Claude Code inside a Textual app, with your buddy animated in a side panel reacting to what you're doing.
- **Hooks**: watches `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SessionStart` to shift mood (idle / attentive / watching / sleeping).
- **Personality-driven speech**: your buddy can occasionally pipe up in character via Claude — wise Owlet quotes proverbs, Dragonling snarls at errors, Moonwyrm speaks in cosmic riddles. Uses your existing Claude Code auth (no separate API key).
- **Talk to your buddy directly**: prefix a line with `~{name}` (e.g. `~quine what color is the sky`) to have your buddy reply instead of Claude.

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

After installing, restart Claude Code so the hooks take effect — Claude reads `~/.claude/settings.json` once at startup, so an already-running session won't see the new hooks. If you skipped the hatch prompt, roll your first buddy with `claude-buddy-hatch` (or `/buddy hatch` inside Claude).

## Usage

Launch the TUI from any terminal:

```bash
claude-buddy
```

Roll a new buddy without opening Claude:

```bash
claude-buddy-hatch          # errors if you already have one
claude-buddy-hatch --peek   # roll without saving
claude-buddy-hatch --force  # re-roll, discarding current
```

Claude Code runs in the main pane; your buddy lives in a panel on the right. Keybindings:

- `Ctrl-Q` — quit
- `Ctrl-B` — toggle the buddy panel
- `Ctrl-S` — toggle the skill grid
- `Ctrl-P` — pet your buddy
- **Scroll wheel** — scroll through the Claude pane's history
- `Shift-PageUp` / `Shift-PageDown` — same, via keyboard
- `Shift-End` — snap back to the live tail
- `~{name} <message>` — talk to your buddy directly (e.g. `~quine hi`). Claude never sees it.

Claude Code slash commands (all work while the TUI is running):

- `/buddy hatch` — roll your first buddy
- `/buddy` — see their card (art, skills, age)
- `/buddy name <name>` — name them
- `/buddy peek` — test-roll without saving (tempting the gacha gods)
- `/buddy quiet` / `/buddy chatty` — toggle whether they speak
- `/buddy forget --confirm` — release them so you can hatch a new one

## How it works

```
┌───────────────────────────────────────────────────────────────┐
│  claude-buddy TUI (Textual)                                   │
│                                                               │
│  ┌──────────────────────────┐   ┌─────────────────────────┐   │
│  │  Claude Code (in a PTY,  │   │  Habitat panel:         │   │
│  │  rendered via pyte)      │   │   sprite, name, XP bar  │   │
│  │                          │   │   speech bubble         │   │
│  │  /buddy commands         │   │                         │   │
│  │  + 5 lifecycle hooks ────┼──▶│  reads state.json       │   │
│  │                          │   │  animates at 10fps      │   │
│  └──────────────────────────┘   └─────────────────────────┘   │
│           writes to ~/.claude/buddy/state.json                │
└───────────────────────────────────────────────────────────────┘
```

Hooks fire on Claude Code events, atomically write `state.json` with mood + current tool, and (optionally) shell out to `claude -p` via `speak.py` for a personality-driven quip. The Textual app polls `state.json` to drive the animation and speech bubble.

## Contributing

PRs welcome! Especially for:
- **New species** — add to `buddy/species.py` (art, skill ranges, signature skill) and `buddy/personality.py` (voice, event weights).
- **Better animations** — tweak `buddy/sprites.py` for mood-specific frames.
- **New moods or hook reactions** — extend the mood logic in `buddy/state.py`.

Open an issue if you have ideas.

## License

BSD 3-Clause. See [LICENSE](LICENSE).
