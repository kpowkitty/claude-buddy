#!/usr/bin/env bash
# Manual installer for claude-buddy (non-plugin install).
# Copies scripts to ~/.claude/buddy/ and merges hooks into ~/.claude/settings.json.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${HOME}/.claude"
BUDDY_DIR="${CLAUDE_DIR}/buddy"
COMMANDS_DIR="${CLAUDE_DIR}/commands"
SETTINGS="${CLAUDE_DIR}/settings.json"

echo "Installing claude-buddy from ${REPO_ROOT}..."

mkdir -p "${BUDDY_DIR}/hooks" "${COMMANDS_DIR}"

# Copy Python scripts
cp "${REPO_ROOT}/buddy/"*.py "${BUDDY_DIR}/"
cp "${REPO_ROOT}/buddy/hooks/"*.py "${BUDDY_DIR}/hooks/"

# Copy slash command (rewriting ${CLAUDE_PLUGIN_ROOT} → actual path)
sed "s|\${CLAUDE_PLUGIN_ROOT}|${CLAUDE_DIR}|g" \
    "${REPO_ROOT}/commands/buddy.md" > "${COMMANDS_DIR}/buddy.md"

# Merge hooks into settings.json
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

echo
echo "Done! Next steps:"
echo "  1. Restart Claude Code so hooks load"
echo "  2. Run /buddy hatch to get your first buddy"
echo "  3. In another terminal: python3 ${BUDDY_DIR}/buddy.py"
