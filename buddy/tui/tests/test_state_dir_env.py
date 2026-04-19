"""Tests for BUDDY_STATE_DIR — the sim-test env var that redirects every
buddy script at a throwaway state directory.

The plumbing is in state.py; every other script imports paths from there.
These tests don't spin up the full TUI — they just confirm the primitive
resolves correctly under different env states.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

# state.py lives at buddy/state.py (one dir up from buddy/tui/, where these
# tests run from). Add it to the path — conftest only adds buddy/tui.
_HERE = Path(__file__).resolve().parent
_BUDDY = _HERE.parent.parent
if str(_BUDDY) not in sys.path:
    sys.path.insert(0, str(_BUDDY))


def _reload_state(monkeypatch, value: str | None) -> object:
    """Force state.py to re-evaluate BUDDY_DIR with the given env value."""
    if value is None:
        monkeypatch.delenv("BUDDY_STATE_DIR", raising=False)
    else:
        monkeypatch.setenv("BUDDY_STATE_DIR", value)
    # Drop any cached import so the module-level assignment re-runs.
    sys.modules.pop("state", None)
    import state  # noqa: WPS433
    return state


def test_default_when_env_unset(monkeypatch) -> None:
    state = _reload_state(monkeypatch, None)
    assert state.BUDDY_DIR == Path.home() / ".claude" / "buddy"
    assert state.IS_TEST_MODE is False


def test_env_var_redirects_buddy_dir(monkeypatch, tmp_path: Path) -> None:
    state = _reload_state(monkeypatch, str(tmp_path))
    assert state.BUDDY_DIR == tmp_path
    assert state.PROGRESSION == tmp_path / "progression.json"
    assert state.STATE == tmp_path / "state.json"
    assert state.IS_TEST_MODE is True


def test_env_var_expands_tilde(monkeypatch) -> None:
    monkeypatch.setenv("BUDDY_STATE_DIR", "~/foo/bar")
    sys.modules.pop("state", None)
    import state  # noqa: WPS433
    assert state.BUDDY_DIR == Path.home() / "foo" / "bar"


def test_empty_env_var_falls_back_to_default(monkeypatch) -> None:
    # Empty string ≠ unset, but should still be treated as "no override".
    monkeypatch.setenv("BUDDY_STATE_DIR", "")
    sys.modules.pop("state", None)
    import state  # noqa: WPS433
    assert state.BUDDY_DIR == Path.home() / ".claude" / "buddy"
    assert state.IS_TEST_MODE is False
