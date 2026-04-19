"""Embedded-terminal Textual widget.

Hosts a subprocess in a PTY, feeds its bytes through a pyte HistoryScreen,
and renders the pyte buffer straight into Textual strips.

Scrollback model: Shift+Wheel / Shift+PageUp/Down pause the pyte feed,
page the screen up through pyte's scrollback (prev_page), and buffer any
output the child emits while paused. Paging back down past the live tail
resumes the feed. Any keystroke also resumes (matches how a real terminal
behaves — type, and you're back at the bottom). Pausing is necessary
because Claude repaints constantly for its spinner / input caret, and
without a pause those repaints would fight the user's scrollback.

No direct coupling to anything buddy-specific: this widget wraps any command.
The app that mounts it is responsible for input routing (so keybindings like
Ctrl-Q can be intercepted before reaching the pty).
"""
from __future__ import annotations

import fcntl
import logging
import os
import pty
import re
import signal
import struct
import termios
from typing import Optional, Sequence

# Strip kitty keyboard-protocol escapes that pyte 0.8.x mis-parses —
# the trailing `u` leaks as literal text. Handles both push (`\x1b[>Pn u`)
# and pop (`\x1b[<u`) forms that Claude emits.
_KITTY_KEYBOARD_RE = re.compile(rb"\x1b\[[<>]\d*u")


def sanitize_pty_bytes(data: bytes) -> bytes:
    """Pre-filter bytes before feeding pyte.

    Removes escape sequences pyte 0.8.x mis-parses. Keep this function pure
    and testable — pty_terminal calls it, tests assert on it directly.
    """
    return _KITTY_KEYBOARD_RE.sub(b"", data)

import pyte
from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.widget import Widget

_log = logging.getLogger("buddy.tui.pty_terminal")

# No bgcolor — blank cells fall through to the widget's background
# (which is `transparent`, letting the user's terminal paint through).
_DEFAULT_STYLE = Style(color="white")

_PYTE_NAMED = {
    "black", "red", "green", "brown", "blue", "magenta", "cyan", "white",
    "brightblack", "brightred", "brightgreen", "brightbrown", "brightblue",
    "brightmagenta", "brightcyan", "brightwhite",
}


def _normalize_color(name, fallback):
    if not name or name == "default":
        return fallback
    if name in _PYTE_NAMED:
        if name == "brown":
            return "yellow"
        if name == "brightbrown":
            return "bright_yellow"
        if name.startswith("bright"):
            return "bright_" + name[len("bright"):]
        return name
    if isinstance(name, str) and len(name) == 6 and all(c in "0123456789abcdefABCDEF" for c in name):
        return "#" + name
    if isinstance(name, str) and name.isdigit():
        return f"color({name})"
    return fallback


def _cell_style(char) -> Style:
    fg = _normalize_color(char.fg, "white")
    # Only set bgcolor when the cell has a real (non-default) background.
    # Leaving it None lets the widget's transparent background show, so
    # the user's terminal (wallpaper, opacity) bleeds through.
    bg_name = _normalize_color(char.bg, None)
    try:
        return Style(
            color=fg,
            bgcolor=bg_name,
            bold=bool(char.bold),
            italic=bool(char.italics),
            reverse=bool(char.reverse),
        )
    except Exception:
        return _DEFAULT_STYLE

_POLL_HZ = 30
_READ_CHUNK = 4096

# Pet overlay geometry. The habitat widget renders sprite(7) + name(1) +
# XP(2) + time(1) + a 7-row bubble reservation in the top-right, totalling
# 18 rows by 24 cols. The L-reflow screen and the adaptive-COLUMNS logic
# both read these. Keep in sync with habitat.HABITAT_WIDTH and the bubble
# height.
PET_W = 24
PET_H = 18

def _effective_child_cols(cols: int, went_wide: bool) -> int:
    """How wide should we tell the child (Claude) the terminal is?

    Start narrow (`cols - PET_W`) so Claude's UI fits alongside the
    floating pet. Once Claude's content has extended below the pet zone
    (LReflowHistoryScreen.content_went_wide), switch to full width — our
    L-reflow wraps any rows that still land in the narrow zone.
    """
    return cols if went_wide else max(20, cols - PET_W)


class PtyTerminal(Widget, can_focus=True):
    """Runs `command` in a pseudo-terminal and renders its output.

    Public API:
      - write_bytes(data): send keystroke bytes to the child
      - is_alive: property, whether the child is still running
      - resize_to(cols, rows): tell the pty about a new size (SIGWINCH)
    """

    DEFAULT_CSS = """
    PtyTerminal {
        background: rgba(0, 0, 0, 0);
        color: white;
    }
    """

    def __init__(self, command: Sequence[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self._command: list[str] = list(command)
        self._pid: Optional[int] = None
        self._fd: Optional[int] = None
        self._screen: Optional[pyte.HistoryScreen] = None
        self._stream: Optional[pyte.ByteStream] = None
        # Scrollback state. When paused, _drain_pty buffers bytes into
        # _paused_buffer instead of feeding pyte — so Claude's repaints
        # don't clobber the scrolled-back view.
        self._paused: bool = False
        self._paused_buffer: bytearray = bytearray()
        # Cached "Claude has gone wide" bit from the last poll of
        # LReflowHistoryScreen.content_went_wide. When this flips vs.
        # the screen's live value, we update Claude's COLUMNS and send
        # Ctrl+L so it repaints at the new width.
        self._last_went_wide: bool = False

    # ── lifecycle ───────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        # Don't spawn yet — wait for the first on_resize after layout stabilizes.
        # This avoids a spawn-then-immediate-resize sequence that corrupts
        # Claude's startup escape stream (splitting a sequence across the
        # resize makes pyte emit literal bytes like a stray 'u').
        pass

    def on_unmount(self) -> None:
        self._stop_pty()

    def _start_pty(self) -> None:
        cols = max(20, self.size.width)
        rows = max(5, self.size.height)
        _log.info("starting pty: cols=%d rows=%d cmd=%r", cols, rows, self._command)
        try:
            with open("/tmp/spike.log", "a") as _dbg:
                import time
                _dbg.write(
                    f"{time.time():.3f} SPAWN cols={cols} rows={rows} "
                    f"widget={self.size.width}x{self.size.height}\n"
                )
        except Exception:
            pass

        # HistoryScreen, not plain Screen: gives us scrollback so when Claude's
        # input box at the bottom grows past the visible area, lines flow into
        # history rather than being silently dropped.
        # `ratio` controls how many lines one prev_page/next_page moves —
        # 0.15 gives a gentler wheel tick than pyte's default half-screen.
        # L-reflow reserves the top-right rectangle so Claude's text
        # wraps around the floating habitat pane. Set BUDDY_LREFLOW=0
        # to fall back to a plain HistoryScreen for debugging — the
        # habitat overlay will then cover live text.
        if os.environ.get("BUDDY_LREFLOW") == "0":
            self._screen = pyte.HistoryScreen(cols, rows, history=2000, ratio=0.15)
        else:
            from lreflow import LReflowHistoryScreen
            # Reserved rectangle: bubble(7) + sprite(7) + name(1) + xp(2)
            # + time(1) = 18 rows, 24 cols (HABITAT_WIDTH). Claude's text
            # wraps at cols-24 in rows 0..17, and at cols from row 18 down.
            # If skills panel is toggled, Claude's text there is occluded
            # under the panel until the user toggles it off — acceptable.
            self._screen = LReflowHistoryScreen(
                cols, rows, pet_w=PET_W, pet_h=PET_H, history=2000, ratio=0.15,
            )
        # Wire query responses (e.g. cursor-position via \x1b[6n) back to the
        # child. Without this, Claude's UI assumes the terminal is unresponsive
        # and falls back to single-line layouts (the AskUserQuestion "Other"
        # field is one example — it stops growing vertically).
        self._screen.write_process_input = self._write_to_child
        self._stream = pyte.ByteStream(self._screen)

        # Claude is told a cols that starts narrow (so its UI fits
        # beside the floating pet) and flips to full width once Claude
        # draws content below the pet zone. On spawn, no content yet,
        # so narrow. The flip is detected in _drain_pty.
        self._last_went_wide = False
        child_cols = _effective_child_cols(cols, went_wide=False)
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        env["LINES"] = str(rows)
        env["COLUMNS"] = str(child_cols)

        try:
            pid, fd = pty.fork()
        except OSError as e:
            _log.error("pty.fork failed: %r", e)
            return

        if pid == 0:
            # Child: detach from parent's async signal state, size the slave
            # pty, then exec. Anything that raises here exits 127.
            try:
                for sig_name in ("SIGINT", "SIGTERM", "SIGQUIT", "SIGWINCH", "SIGHUP", "SIGPIPE"):
                    sig = getattr(signal, sig_name, None)
                    if sig is not None:
                        signal.signal(sig, signal.SIG_DFL)
                signal.set_wakeup_fd(-1)
                winsize = struct.pack("HHHH", rows, child_cols, 0, 0)
                fcntl.ioctl(0, termios.TIOCSWINSZ, winsize)
                os.execvpe(self._command[0], self._command, env)
            except Exception:
                os._exit(127)

        # Parent
        self._pid = pid
        self._fd = fd
        # Non-blocking reads so we don't stall the Textual event loop.
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self.set_interval(1 / _POLL_HZ, self._drain_pty)
        self.refresh()

    def _stop_pty(self) -> None:
        if self._pid:
            try:
                os.kill(self._pid, signal.SIGTERM)
            except Exception:
                pass
            self._pid = None
        if self._fd is not None:
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None

    # ── public API ──────────────────────────────────────────────────────────

    @property
    def is_alive(self) -> bool:
        return self._pid is not None and self._fd is not None

    def write_bytes(self, data: bytes) -> None:
        """Write keystroke bytes to the child process.

        Typing while scrolled back resumes live view first (matches normal
        terminal behaviour — you type, you're back at the bottom).
        """
        if self._fd is None or not data:
            return
        if self._paused:
            self.resume_live()
        try:
            os.write(self._fd, data)
        except OSError as e:
            _log.warning("pty write failed: %r", e)

    def _write_to_child(self, data: str) -> None:
        """Pyte query responses route through here back to the child's stdin."""
        if self._fd is None:
            return
        try:
            os.write(self._fd, data.encode("utf-8", errors="replace"))
        except OSError as e:
            _log.warning("query response write failed: %r", e)

    def resize_to(self, cols: int, rows: int) -> None:
        """Update both pyte's screen and the pty's view of its size.

        Also does an automatic F5-equivalent refresh: wipes pyte's buffer
        and asks Claude to repaint. Without this, a resize that grows the
        widget past PET_H causes `content_went_wide` to flip mid-draw on
        the first subsequent prompt render, producing a visible double-
        line glitch. Refreshing here makes the resize settle before any
        new content arrives.
        """
        if cols <= 0 or rows <= 0:
            return
        try:
            with open("/tmp/spike.log", "a") as _dbg:
                import time
                _dbg.write(
                    f"{time.time():.3f} RESIZE cols={cols} rows={rows} "
                    f"widget={self.size.width}x{self.size.height}\n"
                )
        except Exception:
            pass
        # Drain any pending bytes before resizing so we don't split an
        # escape sequence across the size change.
        self._drain_pty()
        if self._screen is not None:
            self._screen.reset()
            self._screen.resize(rows, cols)
        # reset() clears content_went_wide; preserve whatever width mode
        # we were in before the resize. Fresh terminals (never went wide)
        # stay narrow so Claude's startup card adapts to the small width.
        # Sessions that had gone wide stay wide so a resize doesn't
        # regress Claude to a cramped layout.
        went_wide = self._last_went_wide
        if self._fd is not None:
            child_cols = _effective_child_cols(cols, went_wide=went_wide)
            try:
                winsize = struct.pack("HHHH", rows, child_cols, 0, 0)
                fcntl.ioctl(self._fd, termios.TIOCSWINSZ, winsize)
            except OSError as e:
                _log.warning("TIOCSWINSZ failed: %r", e)
            # Ctrl+L — tell Claude to redraw from scratch at the new size.
            try:
                os.write(self._fd, b"\x0c")
            except OSError:
                pass
        self.refresh()

    def _maybe_flip_width(self) -> None:
        """Check the screen's content_went_wide bit; if it doesn't match
        our last cached value, update Claude's COLUMNS and trigger a
        repaint. Called from _drain_pty after every read."""
        if self._fd is None or self._screen is None:
            return
        current = getattr(self._screen, "content_went_wide", False)
        if current == self._last_went_wide:
            return
        # Transition. Recompute cols, update Claude, clear pyte, Ctrl+L.
        cols = max(20, self.size.width)
        rows = max(5, self.size.height)
        child_cols = _effective_child_cols(cols, went_wide=current)
        try:
            winsize = struct.pack("HHHH", rows, child_cols, 0, 0)
            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, winsize)
        except OSError as e:
            _log.warning("TIOCSWINSZ on width flip failed: %r", e)
        # Clear just the visible screen so stale pixels from the old
        # width don't linger, but keep tab stops / modes / scrollback
        # intact. reset() does a full reinit which causes a visible
        # blank-frame blink. clear_visible() is a bypass that also
        # preserves our content_went_wide flag (so the transition we
        # just detected isn't immediately undone).
        if hasattr(self._screen, "clear_visible"):
            self._screen.clear_visible()
        else:
            self._screen.erase_in_display(2)
        try:
            os.write(self._fd, b"\x0c")
        except OSError:
            pass
        self._last_went_wide = current

    # ── pty I/O ─────────────────────────────────────────────────────────────

    def _drain_pty(self) -> None:
        if self._fd is None or self._stream is None:
            return
        # Drain every pending byte in one pass. If a resize happens mid-escape
        # (between reads), pyte's parser can emit the tail as literal text —
        # e.g., a stray 'u' from \x1b[>1u. Drain-to-empty makes that window tiny.
        while True:
            try:
                data = os.read(self._fd, _READ_CHUNK)
            except BlockingIOError:
                break
            except OSError as e:
                if e.errno == 5:  # EIO — child died
                    _log.info("pty EIO (child exited)")
                    self._fd = None
                elif e.errno == 35:  # EAGAIN
                    break
                else:
                    _log.warning("pty read error: %r", e)
                break
            if not data:
                break
            data = sanitize_pty_bytes(data)
            if self._paused:
                # Stash for replay on resume — don't let Claude repaint over
                # the user's scrolled-back view.
                self._paused_buffer.extend(data)
            else:
                self._stream.feed(data)
        # After feeding, the screen may have flipped narrow↔wide.
        self._maybe_flip_width()
        self.refresh()

    # ── rendering ───────────────────────────────────────────────────────────

    def on_resize(self) -> None:
        # First real resize after layout = time to spawn. Subsequent resizes
        # propagate to the running pty.
        if self._screen is None:
            if self.size.width > 0 and self.size.height > 0:
                self._start_pty()
            return
        cols = max(20, self.size.width)
        rows = max(5, self.size.height)
        if cols != self._screen.columns or rows != self._screen.lines:
            self.resize_to(cols, rows)

    # Claude Code's prompt box top/bottom uses U+2500 (─). When the width
    # flips narrow→wide mid-render, there's a moment where Claude has
    # already emitted a wrapped border at the narrow width — row y is a
    # solid ─ run of length (cols - PET_W), row y+1 starts with more ─
    # (the overflow continuation). Blank the continuation so we don't
    # show a doubled border during the straddle. Cosmetic only; pyte's
    # buffer stays intact.
    _PROMPT_BORDER_CH = "─"

    def _row_is_full_narrow_border(self, y: int) -> bool:
        """True if row y is filled edge-to-edge with the prompt-border
        char across the narrow width (cols - PET_W)."""
        if self._screen is None:
            return False
        if not (0 <= y < self._screen.lines):
            return False
        narrow = max(0, self._screen.columns - PET_W)
        if narrow <= 0:
            return False
        row = self._screen.buffer[y]
        for x in range(narrow):
            if (row[x].data or " ") != self._PROMPT_BORDER_CH:
                return False
        return True

    def _leading_border_run(self, y: int) -> int:
        """How many leading cells of row y hold the prompt-border char."""
        if self._screen is None or not (0 <= y < self._screen.lines):
            return 0
        row = self._screen.buffer[y]
        n = 0
        for x in range(self._screen.columns):
            if (row[x].data or " ") != self._PROMPT_BORDER_CH:
                break
            n += 1
        return n

    def render_line(self, y: int) -> Strip:
        widget_w = self.size.width
        if self._screen is None or not (0 <= y < self._screen.lines):
            return Strip([Segment(" " * widget_w, _DEFAULT_STYLE)])

        # Straddle fix: if the previous row (still in the narrow zone) is
        # a full-narrow-width prompt border, any leading border run on
        # this row is the wrapped overflow — blank it.
        blank_prefix = 0
        if 0 < y <= PET_H and y - 1 < PET_H:
            if self._row_is_full_narrow_border(y - 1):
                blank_prefix = self._leading_border_run(y)

        row = self._screen.buffer[y]
        cols = self._screen.columns
        segments: list[Segment] = []
        cur_text = ""
        cur_style = _DEFAULT_STYLE
        for x in range(cols):
            if x < blank_prefix:
                data = " "
                style = _DEFAULT_STYLE
            else:
                ch = row[x]
                data = ch.data or " "
                style = _cell_style(ch)
            if style == cur_style:
                cur_text += data
            else:
                if cur_text:
                    segments.append(Segment(cur_text, cur_style))
                cur_text = data
                cur_style = style
        if cur_text:
            segments.append(Segment(cur_text, cur_style))
        return Strip(segments)

    # ── scrollback ──────────────────────────────────────────────────────────

    def scroll_history(self, direction: int) -> bool:
        """Page through pyte's scrollback. direction = -1 (back) or +1 (forward).

        On the first back-scroll, pauses the pyte feed so Claude's repaints
        don't clobber the view. Paging past the live tail resumes. Returns
        True if the screen actually moved.
        """
        if self._screen is None:
            return False
        if direction < 0:
            if not self._paused:
                self._paused = True
            before = self._screen.history.position
            self._screen.prev_page()
            moved = self._screen.history.position != before
            if moved:
                self.refresh()
            return moved
        # Forward: page down. If we'd be at (or past) live, resume instead.
        if not self._paused:
            return False
        before = self._screen.history.position
        self._screen.next_page()
        if self._screen.history.position == self._screen.history.size:
            # We're back at the live tail — replay buffered output.
            self.resume_live()
            return True
        moved = self._screen.history.position != before
        if moved:
            self.refresh()
        return moved

    def resume_live(self) -> None:
        """Exit scrollback: flush any buffered output into pyte and unpause."""
        if not self._paused:
            return
        self._paused = False
        if self._stream is not None and self._paused_buffer:
            self._stream.feed(bytes(self._paused_buffer))
        self._paused_buffer.clear()
        self.refresh()

    @property
    def is_paused(self) -> bool:
        return self._paused

    async def on_mouse_scroll_up(self, event) -> None:
        self.scroll_history(-1)
        event.stop()

    async def on_mouse_scroll_down(self, event) -> None:
        self.scroll_history(+1)
        event.stop()
