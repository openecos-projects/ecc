# pyright: strict
"""The ``ecc flow edit`` checkbox: the rich step table, driven by single keys.

The plan is recomputed after every toggle and redrawn with its problems, so a
selection that leaves a step without required design data cannot be saved.
The saved selection is then confirmed before ecc.toml is written.
"""

import os
import sys
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.text import Text

from chipcompiler.cli.project.flow_plan_view import PlanView
from chipcompiler.cli.rendering.flow_selection_view import flow_selection_view

#: Reads the next key presses (one or more); see :func:`terminal_keys`.
KeyReader = Callable[[], str]
#: The view of the flow without the given (canonical) skipped steps.
ViewOf = Callable[[tuple[str, ...]], PlanView]

_UP = frozenset({"\x1b[A", "\x1bOA", "k"})
_DOWN = frozenset({"\x1b[B", "\x1bOB", "j"})
_TOGGLE = frozenset({" ", "x"})
_SAVE = frozenset({"\r", "\n"})
_CANCEL = frozenset({"q", "\x1b", "\x03", "\x04"})
#: Windows reports arrows as a prefix key followed by the scan code.
_WINDOWS_PREFIX = frozenset({"\x00", "\xe0"})
_WINDOWS_ARROWS = {"H": "\x1b[A", "P": "\x1b[B"}
_KEYS = "↑/↓ move · space toggle · enter save · q cancel"
_YES = frozenset({"y", "Y"})
#: Enter keeps ecc.toml as it is: writing needs an explicit ``y``.
_NO = frozenset({"n", "N", *_SAVE, *_CANCEL})
_CONFIRM_KEYS = "y write · n/enter/q cancel"


def edit_selection(
    skip_steps: Sequence[str], *, view_of: ViewOf, console: Console, read_key: KeyReader
) -> tuple[str, ...] | None:
    """Toggle steps until saved (the new skip list) or cancelled (None)."""
    skip = tuple(skip_steps)
    view = view_of(skip)
    cursor = 0
    notice = ""

    def render() -> RenderableType:
        footer = f"{_KEYS}\n{notice}" if notice else _KEYS
        return flow_selection_view(view, cursor=cursor, footer=footer)

    pending: list[str] = []
    with Live(render(), console=console, auto_refresh=False, transient=True) as live:
        while True:
            try:
                while not pending:
                    pending = split_keys(read_key())
                    if pending and pending[-1] in _WINDOWS_PREFIX:
                        pending[-1:] = split_keys(pending[-1] + read_key())
            except (KeyboardInterrupt, EOFError):
                return None
            key = pending.pop(0)
            notice = ""
            if key in _UP:
                cursor = (cursor - 1) % len(view.steps)
            elif key in _DOWN:
                cursor = (cursor + 1) % len(view.steps)
            elif key in _TOGGLE:
                row = view.steps[cursor]
                if row.target:
                    notice = f"{row.step} ends the flow and stays enabled"
                else:
                    skip = _toggled(skip, row.step, [step.step for step in view.steps])
                    view = view_of(skip)
            elif key in _SAVE:
                if not view.blocks_saving:
                    return skip
                notice = "resolve the errors before saving"
            elif key in _CANCEL:
                return None
            live.update(render(), refresh=True)


def confirm_write(summary: RenderableType, *, console: Console, read_key: KeyReader) -> bool:
    """Show *summary* until ``y`` (write) or ``n``/enter/cancel (keep ecc.toml)."""
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
    while the table redraws are kept (``click.getchar`` re-enters raw mode per
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
        elif char in _WINDOWS_PREFIX and index + 1 < len(chunk):
            keys.append(_WINDOWS_ARROWS.get(chunk[index + 1], ""))
            index += 2
        else:
            keys.append(char)
            index += 1
    return keys


def _toggled(skip: tuple[str, ...], name: str, order: Sequence[str]) -> tuple[str, ...]:
    """*skip* with *name* flipped, in chain order."""
    selected = set(skip) ^ {name}
    return tuple(step for step in order if step in selected)
