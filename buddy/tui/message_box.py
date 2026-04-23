"""MessageBox — reusable bordered modal for errors, info, and prompts.

Replaces timer-based footer toasts. The box sits in the middle of the
screen with a rounded border, transparent background (so the pty /
gacha menu / habitat stay visible around it), and an explicit dismiss
key — no auto-close timer.

Three kinds:
  - "error"  : red-tinted border; any single key dismisses (default: q).
  - "info"   : cyan-tinted border; any single key dismisses (default: q).
  - "prompt" : white border; caller provides the valid choice keys; each
               dismisses with ("choice", key). Other keys cancel (returns
               ("cancelled", None)) unless explicitly allowed.

Dismiss payload:
  error / info  → ("closed", None)
  prompt        → ("choice", key)   on a valid choice
                  ("cancelled", None) on a cancel key
"""
from __future__ import annotations

import textwrap
from typing import Iterable, Optional

from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widget import Widget


_KIND_COLOR = {
    "error": "red",
    "info": "cyan",
    "prompt": "white",
}


# Minimum inner dims; the box grows to fit the wrapped body but never
# goes narrower than this. Caller can't shrink below — makes the box
# read as a deliberate interrupt, not a sliver.
_MIN_INNER_W = 30
_MAX_INNER_W = 56
_MIN_INNER_H = 3

# Horizontal breathing room inside the border — one blank column on
# each side of the text so body/footer don't hug the `│`.
_TEXT_PAD = 2


class _MessageStage(Widget):
    """Paints the bordered box. Auto-sized to the wrapped content."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def render_line(self, y: int) -> Strip:
        w = self.size.width
        h = self.size.height
        inner_w = w - 2

        screen: "MessageBox" = self.screen  # type: ignore[assignment]
        color = _KIND_COLOR.get(screen.kind, "white")
        bold = screen.kind == "error"
        border_style = Style(color=color, bold=bold)
        content_style = Style(color=color, bold=bold)

        if y == 0:
            edge = "╭" + "─" * (w - 2) + "╮"
            return Strip([Segment(edge, border_style)])
        if y == h - 1:
            # Footer hint in the bottom rule: shows the dismiss key(s).
            hint = screen.footer_hint
            bar = "─" * (w - 2)
            if hint and len(hint) + 4 <= w - 2:
                pad = (len(bar) - len(hint)) // 2
                bar = "─" * pad + hint + "─" * (len(bar) - pad - len(hint))
            edge = "╰" + bar + "╯"
            return Strip([Segment(edge, border_style)])

        lines = screen.rendered_lines
        inner_y = y - 1
        inner_h = h - 2
        top = max(0, (inner_h - len(lines)) // 2)

        # Text area is inset by _TEXT_PAD columns on each side so prose
        # doesn't touch the border.
        text_w = max(0, inner_w - 2 * _TEXT_PAD)

        if lines and top <= inner_y < top + len(lines):
            line = lines[inner_y - top]
            if len(line) > text_w:
                line = line[:text_w]
            pad_left = max(0, (text_w - len(line)) // 2)
            pad_right = text_w - pad_left - len(line)
            interior = [
                Segment(" " * _TEXT_PAD, Style()),
                Segment(" " * pad_left, Style()),
                Segment(line, content_style),
                Segment(" " * pad_right, Style()),
                Segment(" " * _TEXT_PAD, Style()),
            ]
        else:
            interior = [Segment(" " * inner_w, Style())]

        return Strip(
            [Segment("│", border_style)] + interior + [Segment("│", border_style)]
        )


class MessageBox(ModalScreen):
    """Bordered modal message. Use for errors, info, or short prompts.

    Args:
        body: the message text. Prose is wrapped; embedded newlines split
              into paragraphs.
        kind: "error" | "info" | "prompt".
        choices: for prompts, an iterable of single-character keys that
                 are valid answers. Each dismisses with ("choice", key).
        cancel_keys: for prompts, keys that dismiss with ("cancelled",
                     None). Defaults to ("q", "escape"). Ignored on
                     error/info (those just close on any of cancel_keys).
        footer_hint: optional override for the bottom-border hint. If
                     omitted, one is generated from the choices / dismiss
                     keys.
    """

    DEFAULT_CSS = """
    MessageBox {
        align: center middle;
        background: transparent;
    }
    """

    # BINDINGS are intentionally empty — we handle keys in on_key so the
    # same screen can serve both prompt (needs arbitrary keys) and
    # error/info (needs a simple dismiss) without binding contention.
    BINDINGS: list = []

    def __init__(
        self,
        body: str,
        *,
        kind: str = "info",
        choices: Iterable[str] = (),
        cancel_keys: Iterable[str] = ("q", "escape"),
        footer_hint: Optional[str] = None,
    ) -> None:
        super().__init__()
        if kind not in _KIND_COLOR:
            raise ValueError(f"unknown message-box kind: {kind!r}")
        self.kind = kind
        self._body = body or ""
        self._choices = tuple(choices)
        self._cancel_keys = tuple(cancel_keys)
        self._footer_hint_override = footer_hint
        self._done = False

    # ── layout ──────────────────────────────────────────────────────────

    @property
    def rendered_lines(self) -> list[str]:
        """Wrap the body to the text area width (inner minus side padding).
        Empty source lines preserve paragraph breaks."""
        width = max(1, self._inner_width() - 2 * _TEXT_PAD)
        out: list[str] = []
        for paragraph in self._body.split("\n"):
            if not paragraph:
                out.append("")
                continue
            wrapped = textwrap.wrap(paragraph, width=width) or [paragraph[:width]]
            out.extend(wrapped)
        return out

    @property
    def footer_hint(self) -> str:
        if self._footer_hint_override is not None:
            return self._footer_hint_override
        if self.kind == "prompt" and self._choices:
            choice_str = " / ".join(self._choices)
            return f"  {choice_str}  ·  q cancel  "
        return "  press q to close  "

    def _inner_width(self) -> int:
        """Pick an inner width that fits the longest word and the footer
        hint, accounting for the side padding, clamped to the min/max.

        Inner width = border-to-border interior (excluding the `│` cols).
        Text width = inner_width - 2*_TEXT_PAD, so we size so the text
        area (not the inner) can hold the content."""
        longest_word = max(
            (len(word) for word in self._body.split()),
            default=0,
        )
        hint_len = len(self.footer_hint)
        widest_paragraph = max(
            (len(p) for p in self._body.split("\n")),
            default=0,
        )
        # Footer hint sits on the border rule itself (no side padding),
        # so it only competes with the inner width.
        target = max(
            longest_word + 2 * _TEXT_PAD,
            hint_len + 4,
            min(widest_paragraph + 2 * _TEXT_PAD, _MAX_INNER_W),
        )
        return max(_MIN_INNER_W, min(_MAX_INNER_W, target))

    def compose(self) -> ComposeResult:
        inner_w = self._inner_width()
        lines = self.rendered_lines
        inner_h = max(_MIN_INNER_H, len(lines))
        stage = _MessageStage(id="message-stage")
        stage.styles.width = inner_w + 2
        stage.styles.height = inner_h + 2
        yield stage

    # ── input ───────────────────────────────────────────────────────────

    async def on_key(self, event: events.Key) -> None:
        if self._done:
            return
        key = event.key
        if self.kind == "prompt":
            if key in self._choices:
                event.stop()
                self._finish(("choice", key))
                return
            if key in self._cancel_keys:
                event.stop()
                self._finish(("cancelled", None))
                return
            # Any other key in prompt mode is ignored (don't leak to the
            # screen underneath).
            event.stop()
            return

        # error / info: any cancel key closes; everything else is swallowed.
        if key in self._cancel_keys:
            event.stop()
            self._finish(("closed", None))
            return
        event.stop()

    def _finish(self, payload) -> None:
        if self._done:
            return
        self._done = True
        self.dismiss(payload)
