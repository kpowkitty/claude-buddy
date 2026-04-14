"""pytest config: make buddy/tui importable as flat modules (matches project style)."""
import sys
from pathlib import Path

TUI_DIR = Path(__file__).resolve().parent.parent
if str(TUI_DIR) not in sys.path:
    sys.path.insert(0, str(TUI_DIR))
