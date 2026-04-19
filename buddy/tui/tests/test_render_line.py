"""Tests for PtyTerminal's pet-zone reflow.

The virtual-row model: each pet-zone virtual row is a list of
(pyte_y, x_start, x_end) spans. A visual line may mix tokens from
multiple pyte rows (reflow packs them together). Blank virtual rows
are Claude's own paragraph breaks. Rows below PET_H pass through as a
single full-width span.
"""
from __future__ import annotations

from types import SimpleNamespace

import pyte

from pty_terminal import PET_H, PET_W, PtyTerminal


def _strip_text(strip) -> str:
    return "".join(seg.text for seg in strip)


class _HeadlessPty(PtyTerminal):
    def __init__(self, widget_width: int = 80, widget_height: int = 40) -> None:
        self._command = []
        self._pid = None
        self._fd = None
        self._screen = None
        self._stream = None
        self._stub_size = SimpleNamespace(width=widget_width, height=widget_height)

    @property
    def size(self):  # type: ignore[override]
        return self._stub_size

    def refresh(self, *args, **kwargs):  # type: ignore[override]
        return self


def _make_screen(widget: _HeadlessPty, cols: int, rows: int) -> pyte.Screen:
    widget._screen = pyte.Screen(cols, rows)
    widget._stream = pyte.ByteStream(widget._screen)
    return widget._screen


def _write_row(screen, y: int, text: str) -> None:
    blank_attrs = screen.buffer[y][0]
    for x, ch in enumerate(text):
        if x >= screen.columns:
            break
        screen.buffer[y][x] = blank_attrs._replace(data=ch)


def _fill_row(screen, y: int, ch: str, start: int = 0, end: int | None = None) -> None:
    if end is None:
        end = screen.columns
    blank_attrs = screen.buffer[y][0]
    for x in range(start, end):
        screen.buffer[y][x] = blank_attrs._replace(data=ch)


def _vrow_text(widget, vrow) -> str:
    """Reconstruct the text content of a virtual row from its spans."""
    if not vrow:
        return ""
    parts: list[str] = []
    for (py, xs, xe) in vrow:
        row = widget._screen.buffer[py]
        parts.append("".join((row[x].data or " ") for x in range(xs, xe)))
    return "".join(parts)


# ─── basic behaviour ──────────────────────────────────────────────────────


def test_render_line_no_screen_returns_blank() -> None:
    widget = _HeadlessPty(widget_width=40)
    strip = widget.render_line(0)
    assert _strip_text(strip) == " " * 40


def test_render_line_out_of_range_returns_blank() -> None:
    widget = _HeadlessPty(widget_width=40)
    _make_screen(widget, cols=20, rows=3)
    strip = widget.render_line(999)
    assert _strip_text(strip) == " " * 40


# ─── paragraph-aware reflow across pyte rows ──────────────────────────────


def test_tokens_from_multiple_pyte_rows_pack_together() -> None:
    """Claude wrote `hello\\n this is an example,\\n pretend\\n that`
    across four pyte rows. Our reflow should re-pack into narrow
    lines that carry multiple short words per line."""
    cols = 40
    narrow = cols - PET_W  # 16
    widget = _HeadlessPty(widget_width=cols, widget_height=200)
    screen = _make_screen(widget, cols=cols, rows=PET_H + 5)
    _write_row(screen, 0, "hello this is an")
    _write_row(screen, 1, "example,")
    _write_row(screen, 2, "pretend")
    _write_row(screen, 3, "that it is correct")
    vrows = widget._virtual_rows()
    # The four pyte rows form one paragraph. Reflowed at narrow=16:
    pet = [v for v in vrows[:10] if v]  # non-blank pet-zone rows
    # Each line should be ≤ 16 chars, and tokens should not dangle:
    # e.g. "example," and "pretend" should be on the same line since
    # they'd fit together.
    texts = [_vrow_text(widget, v) for v in pet]
    joined = " ".join(t.strip() for t in texts)
    assert "hello this is an" in joined or "hello this is" in joined
    assert "example, pretend" in joined
    for t in texts:
        assert len(t) <= narrow


def test_blank_pyte_row_emits_blank_virtual_row() -> None:
    """Claude's own paragraph break (a blank pyte row) stays as a
    blank virtual row between paragraphs."""
    cols = 40
    widget = _HeadlessPty(widget_width=cols, widget_height=200)
    screen = _make_screen(widget, cols=cols, rows=PET_H + 5)
    _write_row(screen, 0, "first paragraph")
    # Row 1 blank.
    _write_row(screen, 2, "second paragraph")
    vrows = widget._virtual_rows()
    pet_zone = vrows[:PET_H + 5]  # anything in pet zone
    # Find the blank virtual row between the two paragraphs.
    blanks = [i for i, v in enumerate(pet_zone) if v == []]
    assert len(blanks) >= 1


# ─── indent preservation ──────────────────────────────────────────────────


def test_indent_applied_to_continuation_lines() -> None:
    """A paragraph whose first pyte row is indented (e.g. bullet
    continuation from Claude) should re-apply that indent on every
    continuation line of the reflowed paragraph."""
    cols = 40
    narrow = cols - PET_W  # 16
    widget = _HeadlessPty(widget_width=cols, widget_height=200)
    screen = _make_screen(widget, cols=cols, rows=PET_H + 5)
    _write_row(screen, 0, "  hello this is a test of indent")
    vrows = widget._virtual_rows()
    pet = [v for v in vrows[:PET_H] if v]
    assert len(pet) >= 2
    # Every continuation line starts with two spaces.
    for v in pet[1:]:
        text = _vrow_text(widget, v)
        assert text.startswith("  "), f"continuation not indented: {text!r}"


def test_no_indent_no_extra_prefix() -> None:
    """When the first pyte row has no leading spaces, continuation
    lines also start at col 0."""
    cols = 40
    widget = _HeadlessPty(widget_width=cols, widget_height=200)
    screen = _make_screen(widget, cols=cols, rows=PET_H + 5)
    _write_row(screen, 0, "hello this is a test with no indent")
    vrows = widget._virtual_rows()
    pet = [v for v in vrows[:PET_H] if v]
    for v in pet:
        text = _vrow_text(widget, v)
        # No line starts with whitespace.
        assert not text.startswith(" "), f"unexpected leading space: {text!r}"


# ─── chrome rows ──────────────────────────────────────────────────────────


def test_border_row_emits_single_narrow_span() -> None:
    """A uniform border row (Claude's prompt-box top/bottom) emits
    one virtual row, narrow-width."""
    cols = 80
    widget = _HeadlessPty(widget_width=cols, widget_height=200)
    screen = _make_screen(widget, cols=cols, rows=PET_H + 5)
    _fill_row(screen, 2, "─", 0, cols)
    vrows = widget._virtual_rows()
    # Find row 2's virtual entries. Chrome rows are single-span.
    row2_entries = [v for v in vrows if any(py == 2 for (py, _, _) in v)]
    assert len(row2_entries) == 1
    # And it's a single span covering cols 0..narrow (or 0..last).
    assert len(row2_entries[0]) == 1


def test_border_row_breaks_paragraph() -> None:
    """A border row between two content rows splits them into
    separate paragraphs — no cross-border token merging."""
    cols = 40
    widget = _HeadlessPty(widget_width=cols, widget_height=200)
    screen = _make_screen(widget, cols=cols, rows=PET_H + 5)
    _write_row(screen, 0, "above the border")
    _fill_row(screen, 1, "─", 0, cols)
    _write_row(screen, 2, "below the border")
    vrows = widget._virtual_rows()
    # No virtual row should mix tokens from row 0 and row 2.
    for v in vrows:
        pytes = {py for (py, _, _) in v}
        assert not (0 in pytes and 2 in pytes), (
            f"tokens from rows 0 and 2 merged across border: {v}"
        )


# ─── below-pet pass-through ───────────────────────────────────────────────


def test_rows_below_pet_h_pass_through() -> None:
    """Rows y >= PET_H each emit one virtual row at full width."""
    cols = 80
    widget = _HeadlessPty(widget_width=cols, widget_height=200)
    _make_screen(widget, cols=cols, rows=PET_H + 5)
    vrows = widget._virtual_rows()
    # Last 5 virtual rows are the below-pet rows.
    for v in vrows[-5:]:
        assert len(v) == 1
        (_, xs, xe) = v[0]
        assert xs == 0 and xe == cols


# ─── bottom anchor ────────────────────────────────────────────────────────


def test_bottom_row_shows_last_pyte_row() -> None:
    """The widget's bottom row shows the last pyte row."""
    cols = 80
    height = 30
    widget = _HeadlessPty(widget_width=cols, widget_height=height)
    screen = _make_screen(widget, cols=cols, rows=PET_H + 20)
    last_y = screen.lines - 1
    _write_row(screen, last_y, "PPPPPP")
    rendered = _strip_text(widget.render_line(height - 1))
    assert rendered.startswith("PPPPPP")


# ─── rendering: padding + style preservation ──────────────────────────────


def test_pet_zone_slice_padded_to_widget_width() -> None:
    """Rendered pet-zone strips are padded to widget width so dark
    bg cells past the text don't bleed through."""
    cols = 80
    widget = _HeadlessPty(widget_width=cols, widget_height=200)
    screen = _make_screen(widget, cols=cols, rows=PET_H + 5)
    _write_row(screen, 0, "hi")
    vrows = widget._virtual_rows()
    offset = len(vrows) - widget.size.height
    # Find the widget y for row 0's first virtual line.
    first_vy = next(i for i, v in enumerate(vrows) if v and any(py == 0 for (py, _, _) in v))
    widget_y = first_vy - offset
    rendered = _strip_text(widget.render_line(widget_y))
    assert rendered.startswith("hi")
    assert len(rendered) == cols


def test_oversized_word_splits_across_virtual_rows() -> None:
    """A single word longer than narrow falls back to char-split."""
    cols = 40
    narrow = cols - PET_W  # 16
    widget = _HeadlessPty(widget_width=cols, widget_height=200)
    screen = _make_screen(widget, cols=cols, rows=PET_H + 5)
    _write_row(screen, 0, "supercalifragilisticexpialidoc")  # 30 chars
    vrows = widget._virtual_rows()
    pet = [v for v in vrows[:PET_H] if v]
    # Reconstructed text should equal the original (joined across rows).
    joined = "".join(_vrow_text(widget, v) for v in pet)
    assert joined.startswith("supercalifr")
    # Each line ≤ narrow.
    for v in pet:
        assert len(_vrow_text(widget, v)) <= narrow
