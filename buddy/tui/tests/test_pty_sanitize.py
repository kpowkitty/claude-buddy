"""Tests for pty_terminal.sanitize_pty_bytes.

Regression coverage for the stray-`u` bug: Claude Code emits kitty keyboard-
protocol escapes (`\\x1b[>1u` at startup, `\\x1b[<u` at shutdown), but pyte
0.8.x's CSI parser doesn't recognize `>` / `<` private-param markers with a
`u` terminator and leaks the final `u` as literal text. We pre-strip those
sequences before feeding pyte.

If you're touching the sanitizer or upgrading pyte, make sure these still
pass — and if pyte itself learns to parse kitty keyboard protocol, you can
remove the sanitizer AND these tests together.
"""
from __future__ import annotations

import pyte

from pty_terminal import sanitize_pty_bytes


# ─── the literal sequences Claude emits ──────────────────────────────────


def test_strips_push_kitty_keyboard() -> None:
    # `\x1b[>1u` = push keyboard-protocol flags (Claude sends at startup)
    assert sanitize_pty_bytes(b"\x1b[>1u") == b""


def test_strips_pop_kitty_keyboard() -> None:
    # `\x1b[<u` = pop keyboard-protocol flags (Claude sends at shutdown)
    assert sanitize_pty_bytes(b"\x1b[<u") == b""


def test_strips_with_multi_digit_param() -> None:
    # Future proofing: the protocol allows multi-bit flags like `\x1b[>15u`
    assert sanitize_pty_bytes(b"\x1b[>15u") == b""


def test_strips_with_no_param() -> None:
    # `\x1b[>u` (no digits) is also legal
    assert sanitize_pty_bytes(b"\x1b[>u") == b""


# ─── must NOT strip legitimate content ───────────────────────────────────


def test_preserves_plain_text_containing_u() -> None:
    assert sanitize_pty_bytes(b"just vibing") == b"just vibing"
    assert sanitize_pty_bytes(b"Opus 4.6") == b"Opus 4.6"


def test_preserves_other_csi_escapes() -> None:
    # Standard CSIs ending in u (cursor restore etc) without private markers
    # are intentionally NOT stripped — only the kitty `> / <` variants.
    assert sanitize_pty_bytes(b"\x1b[1;2u") == b"\x1b[1;2u"


def test_preserves_common_claude_escapes() -> None:
    # Sample of things we must pass through untouched.
    for seq in [
        b"\x1b[?25l",         # hide cursor
        b"\x1b[?2004h",       # bracketed paste on
        b"\x1b[?1004h",       # focus reporting on
        b"\x1b[?2031h",       # theme-change reporting
        b"\x1b[>4;2m",        # set modify-other-keys
        b"\x1b[?2026h",       # batched output begin
        b"\x1b[38;2;255;204;0m",  # truecolor fg
        b"\x1b[2J",           # clear screen
        b"\x1b[H",            # cursor home
    ]:
        assert sanitize_pty_bytes(seq) == seq, f"mangled {seq!r}"


# ─── mixed streams (real-world shape) ────────────────────────────────────


def test_strips_within_a_larger_stream() -> None:
    claude_startup = (
        b"\x1b[?25l\x1b[?2004h\x1b[?1004h\x1b[?2031h"
        b"\x1b[>1u"  # ← the problem
        b"\x1b[>4;2m\x1b[?2026h"
    )
    cleaned = sanitize_pty_bytes(claude_startup)
    # The >1u sequence is gone; nothing else changed.
    assert b"\x1b[>1u" not in cleaned
    assert b"\x1b[?25l" in cleaned
    assert b"\x1b[?2026h" in cleaned


def test_strips_multiple_occurrences() -> None:
    # Just in case — both forms in one stream
    data = b"hello\x1b[>1uworld\x1b[<ugoodbye"
    assert sanitize_pty_bytes(data) == b"helloworldgoodbye"


# ─── integration: pyte no longer emits a stray 'u' ───────────────────────


def test_pyte_does_not_emit_stray_u_after_sanitize() -> None:
    """The end-to-end invariant we care about.

    Without the sanitizer, feeding `\\x1b[>1u` to a fresh pyte 0.8.2 screen
    can leak the `u` as literal text at (0, 0). This test asserts the whole
    pipeline (sanitize → feed → inspect) doesn't do that.
    """
    screen = pyte.Screen(40, 5)
    stream = pyte.ByteStream(screen)
    claude_startup = (
        b"\x1b[?25l\x1b[?2004h\x1b[?1004h\x1b[?2031h"
        b"\x1b[>1u"
        b"\x1b[>4;2m\x1b[?2026h"
    )
    stream.feed(sanitize_pty_bytes(claude_startup))
    # Row 0 should be entirely blank; in particular, (0, 0) must not be 'u'.
    for x in range(screen.columns):
        ch = screen.buffer[0][x].data or " "
        assert ch == " ", f"row 0 col {x} is {ch!r} (expected blank)"


def test_sanitizer_is_noop_when_pyte_has_real_u_chars() -> None:
    """Legitimate `u` characters in text must survive and land in the buffer."""
    screen = pyte.Screen(40, 5)
    stream = pyte.ByteStream(screen)
    stream.feed(sanitize_pty_bytes(b"Opus 4.6"))
    text = "".join((screen.buffer[0][x].data or " ") for x in range(8))
    assert text == "Opus 4.6"
