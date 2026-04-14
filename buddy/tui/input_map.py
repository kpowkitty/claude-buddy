"""Map Textual Key events to the bytes a pty child expects.

Rule of thumb: if Textual tells us what character was typed (via
`event.character`), that's authoritative. Otherwise we fall back to a table
of named keys → escape sequences.
"""
from __future__ import annotations

from typing import Protocol


class KeyLike(Protocol):
    """Minimal Textual Key event shape. Lets tests use a plain dataclass."""
    key: str
    character: str | None


_NAMED_KEYS: dict[str, bytes] = {
    "enter": b"\r",
    "return": b"\r",
    "backspace": b"\x7f",
    "tab": b"\t",
    "shift+tab": b"\x1b[Z",
    "escape": b"\x1b",
    "space": b" ",
    "up": b"\x1b[A",
    "down": b"\x1b[B",
    "right": b"\x1b[C",
    "left": b"\x1b[D",
    "home": b"\x1b[H",
    "end": b"\x1b[F",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "delete": b"\x1b[3~",
    "insert": b"\x1b[2~",
    "f1": b"\x1bOP",
    "f2": b"\x1bOQ",
    "f3": b"\x1bOR",
    "f4": b"\x1bOS",
    "f5": b"\x1b[15~",
    "f6": b"\x1b[17~",
    "f7": b"\x1b[18~",
    "f8": b"\x1b[19~",
    "f9": b"\x1b[20~",
    "f10": b"\x1b[21~",
    "f11": b"\x1b[23~",
    "f12": b"\x1b[24~",
}


def key_to_bytes(event: KeyLike) -> bytes | None:
    """Translate a Textual Key event to pty bytes.

    Returns None if the key has no sensible pty representation (e.g. a
    widget-only binding). Callers should treat None as "consume silently."
    """
    # Ctrl combinations: ctrl+<letter> = byte (letter & 0x1f), ctrl+@ = NUL.
    key = event.key
    if key.startswith("ctrl+") and len(key) == len("ctrl+") + 1:
        tail = key[-1]
        if tail == "@":
            return b"\x00"
        if "a" <= tail.lower() <= "z":
            return bytes([ord(tail.lower()) & 0x1f])

    # Printable character: trust event.character.
    ch = getattr(event, "character", None)
    if ch and ch.isprintable():
        return ch.encode("utf-8")

    # Named key fallback.
    return _NAMED_KEYS.get(key)
