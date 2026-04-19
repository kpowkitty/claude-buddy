# Pytest suite

Static automated tests run via `pytest`. This is the correctness harness —
contracts, regressions, edge cases. Runs in CI, run locally before commits.

```
buddy/tui/.venv/bin/pytest buddy/tui/tests/
```

Adding new tests: put them in a `test_*.py` file in this directory. Each
module gets path-rigged by `conftest.py` so `buddy/*.py` modules are
importable. See existing files for patterns.

For hand-play / simulation against a live TUI with canned progression
states, see `buddy/tests/README.md` (different directory, different
purpose).
