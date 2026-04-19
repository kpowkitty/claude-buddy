#!/usr/bin/env bash
# Installer for claude-buddy.
#
# What it does:
#   1. Creates the Python venv at buddy/tui/.venv (if missing) and installs
#      runtime deps from requirements.txt.
#   2. Copies hook scripts to ~/.claude/buddy/ and merges hook entries into
#      ~/.claude/settings.json (idempotent — won't double-register).
#   3. Symlinks bin/claude-buddy into ~/.local/bin/claude-buddy so you can
#      launch from anywhere.
#
# Re-running the installer overwrites scripts in ~/.claude/buddy/ and
# refreshes the symlink. It does NOT touch state.json / prefs.json or the
# venv once it exists. To rebuild the venv, rm -rf buddy/tui/.venv first.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${HOME}/.claude"
BUDDY_DIR="${CLAUDE_DIR}/buddy"
COMMANDS_DIR="${CLAUDE_DIR}/commands"
SETTINGS="${CLAUDE_DIR}/settings.json"
VENV_DIR="${REPO_ROOT}/buddy/tui/.venv"
LAUNCHER_SRC="${REPO_ROOT}/bin/claude-buddy"
LAUNCHER_DST="${HOME}/.local/bin/claude-buddy"
HATCH_SRC="${REPO_ROOT}/bin/claude-buddy-hatch"
HATCH_DST="${HOME}/.local/bin/claude-buddy-hatch"
TESTS_SRC="${REPO_ROOT}/buddy/tests/run"
TESTS_DST="${HOME}/.local/bin/claude-buddy-tests"

echo "Installing claude-buddy from ${REPO_ROOT}..."

# 1. Python venv + deps ──────────────────────────────────────────────────────
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    echo "Creating venv at ${VENV_DIR}..."
    python3 -m venv "${VENV_DIR}"
fi

echo "Installing Python dependencies..."
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --quiet -r "${REPO_ROOT}/requirements.txt"

# 2. Hook scripts + settings merge ──────────────────────────────────────────
echo "Updating installed scripts in ${BUDDY_DIR} (overwrites any local edits there)..."
mkdir -p "${BUDDY_DIR}/hooks" "${COMMANDS_DIR}"
cp "${REPO_ROOT}/buddy/"*.py "${BUDDY_DIR}/"
cp "${REPO_ROOT}/buddy/hooks/"*.py "${BUDDY_DIR}/hooks/"

# Slash command: rewrite ${CLAUDE_PLUGIN_ROOT} → actual path
sed "s|\${CLAUDE_PLUGIN_ROOT}|${CLAUDE_DIR}|g" \
    "${REPO_ROOT}/commands/buddy.md" > "${COMMANDS_DIR}/buddy.md"

if [[ ! -f "${SETTINGS}" ]]; then
    echo '{}' > "${SETTINGS}"
fi

python3 - <<PYEOF
import json, pathlib
settings_path = pathlib.Path("${SETTINGS}")
buddy_dir = "${BUDDY_DIR}"
data = json.loads(settings_path.read_text() or "{}")
data.setdefault("hooks", {})
for event, script in [
    ("UserPromptSubmit", "on_prompt.py"),
    ("PreToolUse",       "on_pre_tool.py"),
    ("PostToolUse",      "on_post_tool.py"),
    ("Stop",             "on_stop.py"),
    ("SessionStart",     "on_session.py"),
]:
    hook_entry = {
        "hooks": [{
            "type": "command",
            "command": f"python3 {buddy_dir}/hooks/{script}",
            "async": True,
        }]
    }
    if event in ("PreToolUse", "PostToolUse"):
        hook_entry["matcher"] = ""
    existing = data["hooks"].setdefault(event, [])
    # Dedup: don't double-register
    if not any(
        any(h.get("command","").endswith(script) for h in e.get("hooks", []))
        for e in existing
    ):
        existing.append(hook_entry)
settings_path.write_text(json.dumps(data, indent=2))
print(f"Merged hooks into {settings_path}")
PYEOF

# 3. Launcher symlinks ──────────────────────────────────────────────────────
mkdir -p "$(dirname "${LAUNCHER_DST}")"
ln -sf "${LAUNCHER_SRC}" "${LAUNCHER_DST}"
ln -sf "${HATCH_SRC}" "${HATCH_DST}"
ln -sf "${TESTS_SRC}" "${TESTS_DST}"
echo "Symlinked ${LAUNCHER_DST} → ${LAUNCHER_SRC}"
echo "Symlinked ${HATCH_DST} → ${HATCH_SRC}"
echo "Symlinked ${TESTS_DST} → ${TESTS_SRC}"

# PATH check
case ":${PATH}:" in
    *":${HOME}/.local/bin:"*)
        path_ok=1
        ;;
    *)
        path_ok=0
        ;;
esac

# 4. Offer to hatch a buddy right now ──────────────────────────────────────
echo
hatched=0
if [[ -t 0 ]]; then
    read -r -p "Hatch a buddy now? [Y/n] " answer || answer=""
    answer="${answer:-Y}"
    if [[ "${answer}" =~ ^[Yy] ]]; then
        echo
        # --tokens on a fresh collection is the starter gift (no token needed
        # until the user has at least one buddy).
        if "${REPO_ROOT}/bin/claude-buddy-hatch" --tokens; then
            hatched=1
        else
            echo "(hatch failed — you can try again later with: claude-buddy-hatch --tokens)" >&2
        fi
    fi
else
    echo "Not a tty — skipping hatch prompt."
fi

# 5. Next steps ────────────────────────────────────────────────────────────
if [[ "${path_ok}" == "1" ]]; then
    launcher_cmd="claude-buddy"
    hatch_cmd="claude-buddy-hatch"
else
    launcher_cmd="${LAUNCHER_DST}"
    hatch_cmd="${HATCH_DST}"
fi

echo
echo "Done!"
if [[ "${hatched}" == "1" ]]; then
    echo "Your buddy is ready. Next:"
    echo "  1. Restart Claude Code so hooks load — it reads ~/.claude/settings.json"
    echo "     once at startup, so a running session won't see the new hooks."
    echo "  2. Launch the TUI with:  ${launcher_cmd}"
else
    echo "Next:"
    echo "  1. Restart Claude Code so hooks load — it reads ~/.claude/settings.json"
    echo "     once at startup, so a running session won't see the new hooks."
    echo "  2. Hatch a buddy:  ${hatch_cmd} --tokens"
    echo "     (or inside Claude Code: /buddy hatch --tokens)"
    echo "  3. Launch the TUI with:  ${launcher_cmd}"
fi

if [[ "${path_ok}" == "0" ]]; then
    echo
    echo "Tip: add ~/.local/bin to your PATH so plain 'claude-buddy' works:"
    echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
fi
