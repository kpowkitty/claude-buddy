"""Tests for PtyTerminal.render_line — the inlined pyte→Strip conversion.

Replaces the old test_reflow.py coverage now that reflow is gone. We stub
Textual's Widget.size (normally set by layout) so we can exercise render_line
without mounting the widget in an App.
"""
from __future__ import annotations

from types import SimpleNamespace

import pyte

from pty_terminal import PtyTerminal


def _strip_text(strip) -> str:
    return "".join(seg.text for seg in strip)


class _HeadlessPty(PtyTerminal):
    def __init__(self, widget_width: int = 40) -> None:
        self._command = []
        self._pid = None
        self._fd = None
        self._screen = None
        self._stream = None
        # Textual layout normally fills this in; stub it for off-app tests.
        self._stub_size = SimpleNamespace(width=widget_width, height=10)

    @property
    def size(self):  # type: ignore[override]
        return self._stub_size

    def refresh(self, *args, **kwargs):  # type: ignore[override]
        return self


def _feed(widget: _HeadlessPty, cols: int, rows: int, text: str) -> None:
    widget._screen = pyte.Screen(cols, rows)
    widget._stream = pyte.ByteStream(widget._screen)
    widget._stream.feed(text.replace("\n", "\r\n").encode())


def test_render_line_no_screen_returns_blank_of_widget_width() -> None:
    widget = _HeadlessPty(widget_width=40)
    # No screen yet.
    strip = widget.render_line(0)
    assert _strip_text(strip) == " " * 40


def test_render_line_plain_text_appears_in_row_zero() -> None:
    widget = _HeadlessPty(widget_width=40)
    _feed(widget, cols=40, rows=5, text="hello world")
    strip = widget.render_line(0)
    assert _strip_text(strip).startswith("hello world")


def test_render_line_width_equals_pyte_columns() -> None:
    """Each rendered row should have exactly `screen.columns` cells.

    The widget width can differ from pyte's columns during a resize race;
    render_line uses pyte's columns so content doesn't overflow onto the
    next row.
    """
    widget = _HeadlessPty(widget_width=40)
    _feed(widget, cols=20, rows=3, text="abc")
    strip = widget.render_line(0)
    assert len(_strip_text(strip)) == 20


def test_render_line_out_of_range_returns_blank() -> None:
    widget = _HeadlessPty(widget_width=40)
    _feed(widget, cols=20, rows=3, text="x")
    # y beyond screen.lines
    strip = widget.render_line(99)
    assert _strip_text(strip) == " " * 40


def test_render_line_multiple_rows() -> None:
    widget = _HeadlessPty(widget_width=40)
    _feed(widget, cols=20, rows=5, text="first\nsecond\nthird")
    assert _strip_text(widget.render_line(0)).startswith("first")
    assert _strip_text(widget.render_line(1)).startswith("second")
    assert _strip_text(widget.render_line(2)).startswith("third")


def test_render_line_after_prev_page_surfaces_scrollback() -> None:
    """With HistoryScreen, render_line should see scrollback content after
    prev_page mutates the visible buffer."""
    widget = _HeadlessPty(widget_width=80)
    widget._screen = pyte.HistoryScreen(80, 10, history=2000)
    widget._stream = pyte.ByteStream(widget._screen)
    widget._stream.feed("\r\n".join(f"line-{i}" for i in range(200)).encode() + b"\r\n")
    live_top = _strip_text(widget.render_line(0))
    widget._screen.prev_page()
    scrolled_top = _strip_text(widget.render_line(0))
    assert live_top != scrolled_top
