"""CLI entrypoint for `claude-buddy`.

Usage:
    claude-buddy [claude-args...]

Launches the Textual app with Claude embedded. Extra args are forwarded to
claude (e.g. `claude-buddy --model opus`).
"""
from __future__ import annotations

import os
import shutil
import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    claude = shutil.which("claude")
    if not claude:
        sys.stderr.write(
            "error: `claude` command not found on PATH. "
            "Install Claude Code first: https://docs.claude.com/claude-code\n"
        )
        return 127

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app import BuddyApp

    BuddyApp([claude, *argv]).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
