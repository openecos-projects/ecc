# pyright: strict
"""Key input shared by the interactive terminal editors.

The terminal stays in cbreak mode for a whole editing session
(:func:`terminal_keys`); each editor reads single key presses
(:func:`next_key`), moves a cursor through a list (:func:`moved`,
:func:`visible_rows`) and may take a line of text (:class:`TextField`).
"""

import os
import sys
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.text import Text

#: Reads the next key presses (one or more); see :func:`terminal_keys`.
KeyReader = Callable[[], str]

UP = frozenset({"\x1b[A", "\x1bOA", "k"})
DOWN = frozenset({"\x1b[B", "\x1bOB", "j"})
LEFT = frozenset({"\x1b[D", "\x1bOD", "-"})
RIGHT = frozenset({"\x1b[C", "\x1bOC", "+"})
PAGE_UP = frozenset({"\x1b[5~"})
PAGE_DOWN = frozenset({"\x1b[6~"})
HOME = frozenset({"\x1b[H", "\x1bOH", "\x1b[1~"})
END = frozenset({"\x1b[F", "\x1bOF", "\x1b[4~"})
ENTER = frozenset({"\r", "\n"})
ESCAPE = "\x1b"
CANCEL = frozenset({"q", ESCAPE, "\x03", "\x04"})
BACKSPACE = frozenset({"\x7f", "\x08"})
#: Clears a text field, as in a shell.
CLEAR_LINE = "\x15"
#: Windows reports arrows as a prefix key followed by the scan code.
WINDOWS_PREFIX = frozenset({"\x00", "\xe0"})
_WINDOWS_ARROWS = {"H": "\x1b[A", "P": "\x1b[B", "K": "\x1b[D", "M": "\x1b[C"}
_YES = frozenset({"y", "Y"})
#: Enter keeps things as they are: writing needs an explicit ``y``.
_NO = frozenset({"n", "N", *ENTER, *CANCEL})
_CONFIRM_KEYS = "y write · n/enter/q cancel"


def next_key(pending: list[str], read_key: KeyReader) -> str:
    """The next key press: the first of *pending*, after reading more when it is empty.

    Raises ``KeyboardInterrupt`` or ``EOFError`` as *read_key* does.
    """
    while not pending:
        pending.extend(split_keys(read_key()))
        if pending and pending[-1] in WINDOWS_PREFIX:
            pending[-1:] = split_keys(pending[-1] + read_key())
    return pending.pop(0)


def moved(cursor: int, key: str, count: int, page: int) -> int | None:
    """The cursor in a list of *count* rows after *key*, or None when it moves nothing.

    ↑/↓ wrap around; page keys move *page* rows; home/end go to either end.
    """
    if key in UP:
        return (cursor - 1) % count
    if key in DOWN:
        return (cursor + 1) % count
    if key in PAGE_UP:
        return max(cursor - page, 0)
    if key in PAGE_DOWN:
        return min(cursor + page, count - 1)
    if key in HOME:
        return 0
    if key in END:
        return count - 1
    return None


def visible_rows(count: int, cursor: int, height: int) -> range:
    """The rows of a list of *count* that *height* lines show, the cursor in view."""
    if count <= height:
        return range(count)
    start = min(max(cursor - height // 2, 0), count - height)
    return range(start, start + height)


@dataclass(slots=True)
class TextField:
    """A line of text typed in the terminal: printable keys add, backspace deletes."""

    text: str = ""

    def feed(self, key: str) -> None:
        if key in BACKSPACE:
            self.text = self.text[:-1]
        elif key == CLEAR_LINE:
            self.text = ""
        elif key.isprintable() and not key.startswith(ESCAPE):
            self.text += key


def confirm_write(summary: RenderableType, *, console: Console, read_key: KeyReader) -> bool:
    """Show *summary* until ``y`` (write) or ``n``/enter/cancel (keep things as they are)."""
    prompt = Group(summary, Text(_CONFIRM_KEYS, style="dim"))
    with Live(prompt, console=console, auto_refresh=False, transient=True):
        while True:
            try:
                keys = split_keys(read_key())
            except (KeyboardInterrupt, EOFError):
                return False
            for key in keys:
                if key in _YES:
                    return True
                if key in _NO:
                    return False


@contextmanager
def terminal_keys() -> Generator[KeyReader]:
    """Key presses from the terminal on stdin, for the whole editing session.

    The terminal stays in cbreak mode until the session ends, so keys typed
    while a screen redraws are kept (``click.getchar`` re-enters raw mode per
    key and flushes them). Windows reads keys one at a time with ``getwch``.
    """
    if sys.platform == "win32":
        import click

        yield click.getchar
        return
    import termios
    import tty

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    encoding = sys.stdin.encoding or "utf-8"
    try:
        yield lambda: os.read(fd, 64).decode(encoding, "replace")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def split_keys(chunk: str) -> list[str]:
    """The key presses in one terminal read.

    A read can hold several keys (typing ahead, a held arrow key, a paste):
    CSI (``ESC [`` ... final byte) and SS3 (``ESC O`` x) sequences stay whole,
    a Windows prefix key joins its scan code, everything else is one key.
    """
    keys: list[str] = []
    index = 0
    while index < len(chunk):
        char = chunk[index]
        if chunk.startswith("\x1b[", index):
            end = index + 2
            while end < len(chunk) and not "@" <= chunk[end] <= "~":
                end += 1
            keys.append(chunk[index : end + 1])
            index = end + 1
        elif chunk.startswith("\x1bO", index) and index + 2 < len(chunk):
            keys.append(chunk[index : index + 3])
            index += 3
        elif char in WINDOWS_PREFIX and index + 1 < len(chunk):
            keys.append(_WINDOWS_ARROWS.get(chunk[index + 1], ""))
            index += 2
        else:
            keys.append(char)
            index += 1
    return keys


def interactive_terminal() -> bool:
    """Whether an editor can run: a terminal it can redraw on both ends.

    ``TERM=dumb`` cannot redraw, and a pipe on either end cannot take keys.
    """
    return sys.stdin.isatty() and sys.stdout.isatty() and not Console().is_dumb_terminal
