"""Tests for input_map.key_to_bytes.

The spike's key handler used `if len(key) == 1: data = key.encode()`, which
missed punctuation because Textual delivers `.`/`,`/`'` with a named `key`
but the actual character in `event.character`. This module's job is to map
Textual's Key event to the bytes a pty child expects.
"""
from __future__ import annotations

from dataclasses import dataclass

from input_map import key_to_bytes


@dataclass
class FakeKey:
    key: str
    character: str | None = None


# ─── printables ──────────────────────────────────────────────────────────────


def test_letters() -> None:
    assert key_to_bytes(FakeKey(key="a", character="a")) == b"a"
    assert key_to_bytes(FakeKey(key="Z", character="Z")) == b"Z"


def test_digits() -> None:
    assert key_to_bytes(FakeKey(key="5", character="5")) == b"5"


def test_space() -> None:
    assert key_to_bytes(FakeKey(key="space", character=" ")) == b" "


def test_punctuation_via_character() -> None:
    # Textual delivers these with a named `key` but the printable in `character`.
    assert key_to_bytes(FakeKey(key="comma", character=",")) == b","
    assert key_to_bytes(FakeKey(key="full_stop", character=".")) == b"."
    assert key_to_bytes(FakeKey(key="apostrophe", character="'")) == b"'"
    assert key_to_bytes(FakeKey(key="semicolon", character=";")) == b";"


def test_symbols_via_character() -> None:
    assert key_to_bytes(FakeKey(key="exclamation_mark", character="!")) == b"!"
    assert key_to_bytes(FakeKey(key="at", character="@")) == b"@"
    assert key_to_bytes(FakeKey(key="question_mark", character="?")) == b"?"


def test_unicode_printable() -> None:
    # e.g., a user pastes an em-dash
    assert key_to_bytes(FakeKey(key="—", character="—")) == "—".encode("utf-8")


# ─── named (non-printable) keys ──────────────────────────────────────────────


def test_enter() -> None:
    assert key_to_bytes(FakeKey(key="enter")) == b"\r"


def test_backspace() -> None:
    assert key_to_bytes(FakeKey(key="backspace")) == b"\x7f"


def test_tab() -> None:
    assert key_to_bytes(FakeKey(key="tab")) == b"\t"


def test_escape() -> None:
    assert key_to_bytes(FakeKey(key="escape")) == b"\x1b"


def test_arrows() -> None:
    assert key_to_bytes(FakeKey(key="up")) == b"\x1b[A"
    assert key_to_bytes(FakeKey(key="down")) == b"\x1b[B"
    assert key_to_bytes(FakeKey(key="right")) == b"\x1b[C"
    assert key_to_bytes(FakeKey(key="left")) == b"\x1b[D"


def test_home_end() -> None:
    assert key_to_bytes(FakeKey(key="home")) == b"\x1b[H"
    assert key_to_bytes(FakeKey(key="end")) == b"\x1b[F"


def test_page_up_down() -> None:
    assert key_to_bytes(FakeKey(key="pageup")) == b"\x1b[5~"
    assert key_to_bytes(FakeKey(key="pagedown")) == b"\x1b[6~"


def test_delete() -> None:
    assert key_to_bytes(FakeKey(key="delete")) == b"\x1b[3~"


# ─── control modifiers ───────────────────────────────────────────────────────


def test_shift_tab() -> None:
    # Claude uses Shift+Tab in plan mode to exit it. Without this mapping
    # it was being silently dropped.
    assert key_to_bytes(FakeKey(key="shift+tab")) == b"\x1b[Z"


def test_ctrl_letter() -> None:
    assert key_to_bytes(FakeKey(key="ctrl+c")) == b"\x03"
    assert key_to_bytes(FakeKey(key="ctrl+d")) == b"\x04"
    assert key_to_bytes(FakeKey(key="ctrl+z")) == b"\x1a"


def test_ctrl_at_and_bracket() -> None:
    # Ctrl-@ (NUL), Ctrl-[ (ESC). Rare but valid.
    assert key_to_bytes(FakeKey(key="ctrl+@")) == b"\x00"


# ─── unsupported / ignored ───────────────────────────────────────────────────


def test_unknown_key_returns_none() -> None:
    assert key_to_bytes(FakeKey(key="f24_custom")) is None


def test_no_character_and_no_mapping_returns_none() -> None:
    assert key_to_bytes(FakeKey(key="mystery")) is None
