# claude-buddy

A gacha-rolled ASCII coding companion for [Claude Code](https://claude.com/claude-code). Hatch one, name them, and they'll live in a second terminal window, watching you code and occasionally piping up with personality-driven remarks.

```
     /\   /\
    (  \_/  )
     \ @.@ /
      > v <  ~~~~
     /     \ ~~~~~
    (_______)

   ★ quine · Kitsune · epic ★
   watching your Bash...
```

## What it does

- **Gacha hatch**: `/buddy hatch` rolls a rarity (common 60% / uncommon 25% / rare 10% / epic 4% / legendary 1%) and a species within that tier. 11 species total.
- **Skills**: every buddy rolls 8 skill stats (wisdom, debugging, refactoring, etc.). Each species has a baseline range and a signature skill that rolls much higher.
- **Lives in a second terminal**: run `python3 buddy/buddy.py` in a separate window and your buddy appears, animated, reacting to Claude Code events.
- **Hooks**: watches `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SessionStart` to shift mood (idle / attentive / watching / sleeping).
- **Personality-driven speech**: your buddy can occasionally pipe up in character via Claude — wise Owlet quotes proverbs, Dragonling snarls at errors, Moonwyrm speaks in cosmic riddles. Uses your existing Claude Code auth (no separate API key).

## Install

### Via Claude Code plugin marketplace (recommended)

```
/plugin marketplace add kpowkitty/claude-buddy
/plugin install claude-buddy@claude-buddy
```

Then restart Claude Code so hooks load.

### Manual install

```bash
git clone https://github.com/kpowkitty/claude-buddy.git
cd claude-buddy
./install.sh
```

## Usage

In Claude Code:

- `/buddy hatch` — roll your first buddy
- `/buddy` — see their card (art, skills, age)
- `/buddy name <name>` — name them
- `/buddy peek` — test-roll without saving (tempting the gacha gods)
- `/buddy quiet` / `/buddy chatty` — toggle whether they speak
- `/buddy forget --confirm` — release them so you can hatch a new one

In a second terminal:

```bash
python3 ~/.claude/plugins/.../buddy/buddy.py
# or if manually installed:
python3 ~/.claude/buddy/buddy.py
```

Press `q` or Ctrl-C to quit the renderer.

## Requirements

- Python 3.9+ (uses stdlib only — `curses`, `json`, `pathlib`)
- Claude Code CLI (`claude`) for personality speech (optional; buddy works silent without it)

## How it works

```
┌─────────────────────────┐         ┌──────────────────────────┐
│  Terminal 1: Claude     │         │  Terminal 2: Buddy       │
│  Code session           │  writes │  Renderer (python3)      │
│                         │  state  │                          │
│  /buddy command         │────────▶│  reads state.json        │
│  + 5 lifecycle hooks    │  ~/.claude/buddy/state.json       │
│                         │         │  animates at 10fps       │
└─────────────────────────┘         └──────────────────────────┘
```

Hooks fire on Claude Code events, atomically write `state.json` with mood + current tool, and optionally spawn `speak.py` which shells out to `claude -p` for a personality-driven quip.

## Contributing

PRs welcome! Especially for:
- **New species** — add to `buddy/species.py` (art, skill ranges, signature skill) and `buddy/personality.py` (voice, event weights).
- **Better animations** — tweak `buddy/sprites.py` for mood-specific frames.
- **New moods or hook reactions** — extend the mood logic in `buddy/state.py`.

Open an issue if you have ideas.

## License

BSD 3-Clause. See [LICENSE](LICENSE).
