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

_POLL_HZ = 60
_READ_CHUNK = 4096

# Pet overlay geometry. The habitat widget renders sprite(7) + name(1) +
# XP(2) + time(1) + a 7-row bubble reservation in the top-right, totalling
# 18 rows by 24 cols. The L-reflow screen and the adaptive-COLUMNS logic
# both read these. Keep in sync with habitat.HABITAT_WIDTH and the bubble
# height.
PET_W = 24
PET_H = 18

def _effective_child_cols(cols: int, went_wide: bool, habitat_visible: bool = True) -> int:
    """How wide should we tell the child (Claude) the terminal is?

    Start narrow (`cols - PET_W`) so Claude's UI fits alongside the
    floating pet. Once Claude's content has extended below the pet zone
    (LReflowHistoryScreen.content_went_wide), switch to full width — our
    L-reflow wraps any rows that still land in the narrow zone. When
    the habitat is hidden (F4 toggle), always report full width.
    """
    if not habitat_visible:
        return cols
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
        # When the habitat panel is hidden (F4), Claude has the full
        # terminal width and no L-shape reflow is needed. The app sets
        # this via set_habitat_visible(); the PTY uses it to skip the
        # pet-zone narrow wrap and render every row full-width.
        self._habitat_visible: bool = True
        # Pending pty writes buffer + async drain task. Large pastes
        # would block the event loop if we wrote synchronously (the
        # pty master blocks when the kernel buffer fills and Claude
        # hasn't drained it yet). Instead we queue bytes here and
        # drain in an async task that yields between chunks.
        self._write_queue: bytearray = bytearray()
        self._write_task = None

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
        child_cols = _effective_child_cols(cols, went_wide=False, habitat_visible=self._habitat_visible)
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

    def set_habitat_visible(self, visible: bool) -> None:
        """Toggle the L-shape reflow at render time only.

        Claude is never informed — its COLUMNS stays narrow throughout
        the session, so content it emits keeps fitting alongside where
        the panel would be. When the habitat is hidden, our renderer
        just stops wrapping and renders pyte's existing buffer at full
        width (content past the narrow zone is blank space, which
        looks fine). No SIGWINCH, no Ctrl+L, no retransmit → no blink.
        """
        if self._habitat_visible == visible:
            return
        self._habitat_visible = visible
        self.refresh()

    def write_bytes(self, data: bytes) -> None:
        """Write keystroke bytes to the child process.

        Typing while scrolled back resumes live view first (matches normal
        terminal behaviour — you type, you're back at the bottom).
        """
        if self._fd is None or not data:
            return
        if self._paused:
            self.resume_live()
        self._enqueue_write(data)

    def _write_to_child(self, data: str) -> None:
        """Pyte query responses route through here back to the child's stdin."""
        if self._fd is None:
            return
        self._enqueue_write(data.encode("utf-8", errors="replace"))

    def _enqueue_write(self, data: bytes) -> None:
        """Queue bytes for async draining. Small writes (typical keystrokes)
        fit in one os.write and return immediately; large writes (a paste
        of tens of KB) would otherwise fill the pty buffer and block the
        event loop while Claude processes them. Draining from a worker
        task lets the UI keep rendering."""
        self._write_queue.extend(data)
        # exclusive=True in the "pty-write" group means Textual will
        # serialize writes — if a drain worker is already running it
        # stays running (new bytes just got appended to the queue it's
        # reading from); if not, run_worker spins up a fresh one.
        if self._write_task is None or self._write_task.is_finished:
            self._write_task = self.run_worker(
                self._drain_write_queue(), exclusive=True, group="pty-write"
            )

    async def _drain_write_queue(self) -> None:
        """Flush self._write_queue to the pty, yielding between chunks
        so Textual can render. Handles partial writes (kernel buffer
        full → retry after a yield) without blocking the event loop."""
        import asyncio
        # Chunk size that typically fits in one PTY buffer on Linux so
        # each os.write is one-shot. Large pastes get split into many
        # chunks, each separated by a yield to the event loop.
        CHUNK = 4096
        while self._write_queue and self._fd is not None:
            view = memoryview(bytes(self._write_queue[:CHUNK]))
            try:
                n = os.write(self._fd, view)
            except BlockingIOError:
                # Buffer full. Yield, let Claude drain, retry.
                await asyncio.sleep(0.002)
                continue
            except OSError as e:
                _log.warning("pty write failed: %r", e)
                self._write_queue.clear()
                return
            if n <= 0:
                await asyncio.sleep(0.002)
                continue
            del self._write_queue[:n]
            # Yield every chunk so the app stays responsive even on
            # megabyte-sized pastes.
            await asyncio.sleep(0)

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
            child_cols = _effective_child_cols(cols, went_wide=went_wide, habitat_visible=self._habitat_visible)
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
        child_cols = _effective_child_cols(cols, went_wide=current, habitat_visible=self._habitat_visible)
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

    # Box-drawing chars Claude uses for UI chrome (prompt-box borders,
    # dividers). A pet-zone row containing any of these is treated as
    # non-wrappable chrome: emit the narrow slice as-is, no reflow.
    _BORDER_CHARS = frozenset("─━│┃┄┅┆┇┈┉┊┋┌┍┎┏┐┑┒┓└┕┖┗┘┙┚┛├┤┬┴┼═║╭╮╯╰╴╵╶╷")

    # A virtual row is a list of (pyte_y, x_start, x_end) spans. Each
    # span's cells are rendered with their original styles (read from
    # pyte's buffer at pyte_y, x). An empty span list means a blank
    # virtual row. Multi-span rows happen when reflow packs tokens
    # from several pyte rows onto one visual line.
    # VirtualRow = list[tuple[int, int, int]]

    def _row_is_blank(self, y: int, cols: int) -> bool:
        row = self._screen.buffer[y]
        for x in range(cols):
            if (row[x].data or " ") != " ":
                return False
        return True

    def _row_has_border(self, y: int, cols: int) -> bool:
        row = self._screen.buffer[y]
        for x in range(cols):
            if (row[x].data or " ") in self._BORDER_CHARS:
                return True
        return False

    def _row_last_nonblank(self, y: int, cols: int) -> int:
        row = self._screen.buffer[y]
        last = cols
        while last > 0 and (row[last - 1].data or " ") == " ":
            last -= 1
        return last

    def _row_leading_indent(self, y: int, cols: int) -> int:
        """Count leading spaces on row y (up to cols)."""
        row = self._screen.buffer[y]
        n = 0
        while n < cols and (row[n].data or " ") == " ":
            n += 1
        return n

    def _tokenize_row(self, y: int, x_start: int, x_end: int) -> list[tuple[int, int]]:
        """Break row y's cells [x_start..x_end) into tokens.

        Alternating non-space and space runs. Non-space runs keep any
        glued-on punctuation (`word,` stays one token), so ride-along
        punctuation wraps with its word.
        """
        row = self._screen.buffer[y]
        tokens: list[tuple[int, int]] = []
        x = x_start
        while x < x_end:
            start = x
            if (row[x].data or " ") == " ":
                while x < x_end and (row[x].data or " ") == " ":
                    x += 1
            else:
                while x < x_end and (row[x].data or " ") != " ":
                    x += 1
            tokens.append((start, x))
        return tokens

    # Sentinel span used to insert a synthetic single space between
    # tokens from adjacent pyte rows that didn't end/start with one.
    # render_line emits a literal " " (default style) for spans with
    # pyte_y == -1.
    _SYNTHETIC_SPACE: tuple[int, int, int] = (-1, 0, 1)

    def _reflow_paragraph(
        self,
        pyte_ys: list[int],
        cols: int,
        narrow: int,
    ) -> list[list[tuple[int, int, int]]]:
        """Reflow a run of consecutive non-blank content pyte rows into
        narrow-width virtual rows.

        Concatenates all tokens from the given pyte rows into one
        stream (ignoring pyte's line breaks — we're re-wrapping
        anyway), then token-packs into lines of at most `narrow`
        cells. Preserves the first row's leading indent as the
        paragraph indent applied to every continuation line.

        Each returned virtual row is a list of (pyte_y, x_start, x_end)
        spans. A single visual line may span multiple pyte rows when
        reflow packs tokens across Claude's row boundaries.
        """
        # Claude Code's continuation lines are consistently indented
        # to col 2 (bullets, numbered lists, wrapped prose all use
        # the same hanging indent). Match that: wrapped lines get a
        # 2-space prefix. First line keeps whatever prefix Claude
        # wrote (bullet, nothing, deeper indent) via start=0 in the
        # gather loop below.
        indent = 2
        # Gather tokens from every row in document order. Row 0's
        # content starts at col 0 so its natural prefix (bullet,
        # leading indent, whatever Claude wrote) is preserved on the
        # first emitted line. Continuation rows skip their own leading
        # indent — our paragraph-level indent re-applies on wrapped
        # lines instead. Insert a synthetic space between adjacent
        # rows whose tokens don't already end/start with one.
        all_tokens: list[tuple[int, int, int]] = []
        for i, y in enumerate(pyte_ys):
            last = self._row_last_nonblank(y, cols)
            start = 0 if i == 0 else self._row_leading_indent(y, cols)
            row_tokens = self._tokenize_row(y, start, last)
            if i > 0 and row_tokens and all_tokens:
                prev = all_tokens[-1]
                prev_ends_space = (
                    prev != self._SYNTHETIC_SPACE
                    and (self._screen.buffer[prev[0]][prev[2] - 1].data or " ") == " "
                )
                first_ts = row_tokens[0][0]
                first_is_space = (self._screen.buffer[y][first_ts].data or " ") == " "
                if not prev_ends_space and not first_is_space:
                    all_tokens.append(self._SYNTHETIC_SPACE)
            for (ts, te) in row_tokens:
                all_tokens.append((y, ts, te))

        # Find a pyte row whose first `indent` cells are all spaces
        # and source the indent span from there. For a bullet paragraph
        # like `● text...`, row 0's first cells are `●` + ` `, not
        # usable as indent — but row 1 (Claude's continuation) starts
        # with the real leading spaces. Fall back to None (a span list
        # entry of (-1, 0, indent) is a synthetic space run).
        indent_span = None
        if indent > 0:
            for y in pyte_ys:
                row = self._screen.buffer[y]
                if all((row[x].data or " ") == " " for x in range(indent)):
                    indent_span = (y, 0, indent)
                    break
            if indent_span is None:
                # Use the synthetic-space sentinel to paint `indent`
                # default-style spaces.
                indent_span = (-1, 0, indent)

        vrows: list[list[tuple[int, int, int]]] = []
        current: list[tuple[int, int, int]] = []
        current_w = 0
        is_first_line = True  # first emitted virtual row — no indent prefix.

        def _start_line() -> None:
            nonlocal current, current_w
            current = []
            current_w = 0
            if indent_span is not None and not is_first_line:
                current.append(indent_span)
                current_w = indent

        def _flush() -> None:
            nonlocal current, current_w, is_first_line
            if current:
                vrows.append(current)
                is_first_line = False
            current = []
            current_w = 0

        _start_line()
        for (py, ts, te) in all_tokens:
            tlen = te - ts
            if py == -1:
                is_space = True
            else:
                is_space = (self._screen.buffer[py][ts].data or " ") == " "
            if is_space:
                # Space token: extend the current line if it fits;
                # otherwise break and drop the space (don't carry it
                # to the new line — new lines get the paragraph indent).
                if current_w + tlen <= narrow:
                    current.append((py, ts, te))
                    current_w += tlen
                else:
                    _flush()
                    _start_line()
                continue
            # Word token.
            # Oversized = longer than the available room on a fresh
            # indented line. That word will never fit on any line
            # cleanly, so fall back to char-splitting it.
            if tlen > narrow - indent:
                if current_w > indent:
                    _flush()
                    _start_line()
                cur = ts
                while cur < te:
                    room = narrow - current_w
                    nxt = min(cur + room, te)
                    current.append((py, cur, nxt))
                    current_w += nxt - cur
                    cur = nxt
                    if cur < te:
                        _flush()
                        _start_line()
                continue
            # Fits on the current line?
            if current_w + tlen <= narrow:
                current.append((py, ts, te))
                current_w += tlen
            else:
                # Wrap onto a fresh (indented) line.
                _flush()
                _start_line()
                current.append((py, ts, te))
                current_w += tlen
        _flush()
        return vrows

    # How close to the right edge a row must end for us to treat it
    # as a Claude-wrapped continuation. Small slack (<4 cols) lets us
    # still detect wraps where Claude avoided splitting a trailing
    # word — that row ends a few cols shy but was clearly a wrap.
    _CLAUDE_WRAP_SLACK = 4

    def _looks_claude_wrapped(self, y: int, cols: int) -> bool:
        """True if pyte row y appears to be a Claude-wrapped row —
        content reaches (or nearly reaches) the right edge, so the
        next row is probably a continuation."""
        last = self._row_last_nonblank(y, cols)
        return last > 0 and cols - last <= self._CLAUDE_WRAP_SLACK

    def _pet_zone_virtual_rows(self, cols: int, narrow: int) -> list[list[tuple[int, int, int]]]:
        """Build virtual rows for pyte rows 0..PET_H-1.

        A paragraph is a run of consecutive non-blank non-chrome pyte
        rows where every row except possibly the last reaches the
        right edge (Claude wrapped them). We concatenate + re-wrap
        those together, because Claude's row breaks inside a wrapped
        paragraph are layout artifacts, not semantic.

        Rows that don't reach the right edge are standalone: Claude
        ended the line deliberately (diff entry, short code line,
        bullet item). They get reflowed on their own — never merged
        with the next row.

        Blank pyte rows emit an empty virtual row; chrome rows emit a
        single-span narrow slice.
        """
        out: list[list[tuple[int, int, int]]] = []
        paragraph: list[int] = []

        def _flush_paragraph() -> None:
            if paragraph:
                out.extend(self._reflow_paragraph(paragraph, cols, narrow))
                paragraph.clear()

        for y in range(PET_H):
            if y >= self._screen.lines:
                break
            if self._row_is_blank(y, cols):
                _flush_paragraph()
                out.append([])
                continue
            if self._row_has_border(y, cols):
                _flush_paragraph()
                last = self._row_last_nonblank(y, cols)
                end = min(last, narrow) if last > 0 else narrow
                out.append([(y, 0, end)])
                continue
            # Content row. A paragraph continues onto this row only if
            # the previous row reached the right edge. Otherwise the
            # previous row stood alone — flush it, start a new one here.
            if paragraph and not self._looks_claude_wrapped(paragraph[-1], cols):
                _flush_paragraph()
            paragraph.append(y)
        _flush_paragraph()
        return out

    def _virtual_rows(self) -> list[list[tuple[int, int, int]]]:
        """Build the full virtual-row list for the widget.

        Pet-zone rows (0..PET_H-1) get paragraph-aware reflow — tokens
        from consecutive content rows are packed into fresh narrow
        lines, blanks preserved as paragraph breaks, chrome rows
        char-split. Rows below PET_H emit a single full-width span
        each (no reflow).
        """
        if self._screen is None:
            return []
        cols = self._screen.columns
        # When the habitat is hidden, Claude owns the full width and we
        # pass every row through as a single full-width span. No reflow,
        # no narrow wrap — Claude's own layout takes over.
        if not self._habitat_visible:
            return [[(y, 0, cols)] for y in range(self._screen.lines)]
        narrow = max(0, cols - PET_W)
        if narrow == 0 or narrow >= cols:
            return [[(y, 0, cols)] for y in range(self._screen.lines)]

        out = self._pet_zone_virtual_rows(cols, narrow)
        for y in range(PET_H, self._screen.lines):
            out.append([(y, 0, cols)])
        return out

    def render_line(self, y: int) -> Strip:
        widget_w = self.size.width
        widget_h = self.size.height
        if self._screen is None:
            return Strip([Segment(" " * widget_w, _DEFAULT_STYLE)])

        # Anchor the virtual-row list to the bottom of the widget so
        # Claude's prompt (which lives at the bottom of pyte's buffer)
        # stays pinned to the widget's bottom no matter how the pet
        # zone reflows. Rows above the visible window are scrolled off
        # the top — they sit behind the habitat overlay anyway.
        vrows = self._virtual_rows()
        offset = len(vrows) - widget_h
        vy = y + offset
        if not (0 <= vy < len(vrows)):
            return Strip([Segment(" " * widget_w, _DEFAULT_STYLE)])

        spans = vrows[vy]
        # A span list is the multi-source content of this virtual row.
        # An empty list is a blank row (Claude's paragraph break).
        # For each span, we read cells at (pyte_y, x) and carry their
        # original style. is_pet_zone rows pad to widget_w so any
        # residual dark bg (from Claude's prompt box) doesn't paint.
        is_pet_zone = all(py < PET_H for (py, _, _) in spans) if spans else True

        # Trim trailing blanks on the last span only (so mid-line
        # space tokens stay intact). Pet-zone rows are padded to
        # widget_w with default-style spaces so residual dark bg
        # from Claude's prompt box doesn't bleed through past the
        # content.
        spans = list(spans)
        if is_pet_zone and spans and spans[-1][0] != -1:
            py, xs, xe = spans[-1]
            row = self._screen.buffer[py]
            while xe > xs and (row[xe - 1].data or " ") == " ":
                xe -= 1
            if xe == xs:
                spans.pop()
            else:
                spans[-1] = (py, xs, xe)

        segments: list[Segment] = []
        cur_text = ""
        cur_style = _DEFAULT_STYLE
        rendered_w = 0
        for (py, xs, xe) in spans:
            if py == -1:
                data = " " * (xe - xs)
                if cur_style == _DEFAULT_STYLE:
                    cur_text += data
                else:
                    if cur_text:
                        segments.append(Segment(cur_text, cur_style))
                    cur_text = data
                    cur_style = _DEFAULT_STYLE
                rendered_w += xe - xs
                continue
            row = self._screen.buffer[py]
            for x in range(xs, xe):
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
                rendered_w += 1
        if cur_text:
            segments.append(Segment(cur_text, cur_style))
        if is_pet_zone and widget_w > rendered_w:
            segments.append(Segment(" " * (widget_w - rendered_w), _DEFAULT_STYLE))
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
