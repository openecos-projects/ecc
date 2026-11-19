# pyright: strict
"""The ``ecc param edit`` editor: parameter groups, then their values, driven by single keys.

Values are typed as ``ecc param apply --set KEY=VALUE`` takes them and are
checked as they are entered. Edits stay pending (``*``) until saved; the
caller confirms them and applies them as one ``ecc param apply`` batch.
``u`` resets a value this scope overrides (``●``) to its base, or drops a
pending edit.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.table import Table
from rich.text import Text

from chipcompiler.cli.interactive.terminal import (
    CANCEL,
    ENTER,
    ESCAPE,
    LEFT,
    KeyReader,
    TextField,
    moved,
    next_key,
    visible_rows,
)

#: The error that keeps the text from being a value of the parameter, or None.
Check = Callable[[str, str], str | None]

_GROUP_KEYS = "↑/↓ move · enter open · s save · q cancel"
_PARAM_KEYS = "↑/↓ move · enter edit · u reset · / filter · ← groups · s save · q cancel"
_SINGLE_GROUP_KEYS = "↑/↓ move · enter edit · u reset · / filter · s save · q cancel"
_TEXT_KEYS = "enter accept · esc cancel"
_SAVE = frozenset({"s"})
_RESET = frozenset({"u"})
_FILTER = frozenset({"/"})
#: Lines the title, header, footer and description take around the rows.
_CHROME = 9


@dataclass(frozen=True, slots=True)
class ParamRow:
    """One parameter as the editor shows it.

    *value* is the current value as text (what ``--set`` takes); *base* the
    value without this scope's override, which *overridden* says it has.
    """

    param: str
    group: str
    value: str
    base: str
    overridden: bool
    kind: str
    hint: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class ParamChanges:
    """What the editor saved: values to set (``KEY``, text) and overrides to remove."""

    sets: tuple[tuple[str, str], ...]
    unsets: tuple[str, ...]


def edit_parameters(
    rows: Sequence[ParamRow],
    *,
    title: str,
    check: Check,
    console: Console,
    read_key: KeyReader,
) -> ParamChanges | None:
    """Edit *rows* until saved (the changes) or cancelled (None).

    With one group the values show directly; otherwise the groups come first.
    """
    editor = _Editor(list(rows), title, check, console.height)
    pending: list[str] = []
    with Live(editor.render(), console=console, auto_refresh=False, transient=True) as live:
        while True:
            try:
                key = next_key(pending, read_key)
            except (KeyboardInterrupt, EOFError):
                return None
            outcome = editor.press(key)
            if not isinstance(outcome, _Continue):
                return outcome
            live.update(editor.render(), refresh=True)


class _Continue:
    """The editor goes on after a key."""


_CONTINUE = _Continue()


class _Editor:
    def __init__(self, rows: list[ParamRow], title: str, check: Check, height: int) -> None:
        self.rows = rows
        self.title = title
        self.check = check
        self.page = max(height - _CHROME, 3)
        self.groups = list(dict.fromkeys(row.group for row in rows))
        self.group = self.groups[0] if len(self.groups) == 1 else None
        self.group_cursor = 0
        self.cursor = 0
        #: Parameter -> text to set, or None to remove the override.
        self.pending: dict[str, str | None] = {}
        self.filter = ""
        #: The field being typed, and what it is for ("value" or "filter").
        self.field: TextField | None = None
        self.field_for = ""
        self.notice = ""
        self.discarding = False

    # -- keys ---------------------------------------------------------------

    def press(self, key: str) -> "ParamChanges | None | _Continue":
        self.notice, discarding = "", self.discarding
        self.discarding = False
        if self.field is not None:
            self._type(key)
        elif key in _SAVE:
            if self.pending:
                return self._changes()
            self.notice = "no changes to save"
        elif key in CANCEL and not (key == ESCAPE and self._in_group()):
            if not self.pending or discarding:
                return None
            self.discarding = True
            self.notice = f"{len(self.pending)} unsaved change(s): press q again to discard"
        elif self.group is None:
            self._press_in_groups(key)
        else:
            self._press_in_values(key)
        return _CONTINUE

    def _in_group(self) -> bool:
        """Whether esc goes back to the groups rather than cancelling."""
        return self.group is not None and len(self.groups) > 1

    def _press_in_groups(self, key: str) -> None:
        if (cursor := moved(self.group_cursor, key, len(self.groups), self.page)) is not None:
            self.group_cursor = cursor
        elif key in ENTER:
            self.group = self.groups[self.group_cursor]
            self.cursor = 0
            self.filter = ""

    def _press_in_values(self, key: str) -> None:
        shown = self._shown()
        if shown and (cursor := moved(self.cursor, key, len(shown), self.page)) is not None:
            self.cursor = cursor
        elif (key in LEFT or key == ESCAPE) and len(self.groups) > 1:
            self.group = None
        elif key in _FILTER:
            self.field, self.field_for = TextField(self.filter), "filter"
        elif not shown:
            self.notice = "no parameter matches the filter" if self.filter else ""
        elif key in ENTER:
            row = shown[self.cursor]
            self.field, self.field_for = TextField(self._text(row)), "value"
        elif key in _RESET:
            self._reset(shown[self.cursor])

    def _type(self, key: str) -> None:
        field = self.field
        assert field is not None
        if key == ESCAPE or key in {"\x03", "\x04"}:
            if self.field_for == "filter":
                self.filter = ""
            self.field = None
        elif key in ENTER:
            if self.field_for == "filter":
                self.filter, self.cursor, self.field = field.text, 0, None
            else:
                self._accept(self._shown()[self.cursor], field.text)
        else:
            field.feed(key)
            if self.field_for == "filter":
                self.filter, self.cursor = field.text, 0

    def _accept(self, row: ParamRow, text: str) -> None:
        error = self.check(row.param, text)
        if error:
            self.notice = error
            return
        self.field = None
        if text == row.value:
            self.pending.pop(row.param, None)
        else:
            self.pending[row.param] = text

    def _reset(self, row: ParamRow) -> None:
        if row.param in self.pending:
            del self.pending[row.param]
        elif row.overridden:
            self.pending[row.param] = None
        else:
            self.notice = f"{row.param} keeps its base value"

    def _changes(self) -> ParamChanges:
        order = [row.param for row in self.rows]
        changed = sorted(self.pending, key=order.index)
        return ParamChanges(
            sets=tuple(
                (param, text) for param in changed if (text := self.pending[param]) is not None
            ),
            unsets=tuple(param for param in changed if self.pending[param] is None),
        )

    # -- drawing ------------------------------------------------------------

    def _shown(self) -> list[ParamRow]:
        needle = self.filter.casefold()
        return [
            row for row in self.rows if row.group == self.group and needle in row.param.casefold()
        ]

    def _text(self, row: ParamRow) -> str:
        """The value *row* has with the pending edits."""
        if row.param not in self.pending:
            return row.value
        text = self.pending[row.param]
        return row.base if text is None else text

    def render(self) -> RenderableType:
        if self.group is None:
            body, keys = self._group_table(), _GROUP_KEYS
        else:
            body = self._value_table()
            keys = _PARAM_KEYS if len(self.groups) > 1 else _SINGLE_GROUP_KEYS
        parts: list[RenderableType] = [Text(self.title, style="bold"), body]
        if self.group is not None and (shown := self._shown()):
            row = shown[min(self.cursor, len(shown) - 1)]
            parts.append(Text(f"{row.param}: {row.description or row.kind}", style="dim"))
        if self.field is not None:
            label = "filter" if self.field_for == "filter" else "value"
            parts.append(Text(f"{label}> {self.field.text}▏", style="bold"))
            keys = _TEXT_KEYS
        if self.pending:
            parts.append(Text(f"{len(self.pending)} pending change(s)", style="yellow"))
        if self.notice:
            parts.append(Text(self.notice, style="red"))
        parts.append(Text(keys, style="dim"))
        return Group(*parts)

    def _group_table(self) -> Table:
        table = Table(box=None, pad_edge=False, header_style="bold")
        for column in ("", "Group", "Parameters", "Overridden", "Pending"):
            table.add_column(column)
        for index in visible_rows(len(self.groups), self.group_cursor, self.page):
            group = self.groups[index]
            members = [row for row in self.rows if row.group == group]
            table.add_row(
                "›" if index == self.group_cursor else " ",
                group,
                str(len(members)),
                str(sum(row.overridden for row in members) or ""),
                str(sum(row.param in self.pending for row in members) or ""),
                style="reverse" if index == self.group_cursor else None,
            )
        return table

    def _value_table(self) -> RenderableType:
        shown = self._shown()
        heading = f"{self.group}" + (f"  (filter: {self.filter})" if self.filter else "")
        table = Table(box=None, pad_edge=False, header_style="bold", title_justify="left")
        for column in ("", "Parameter", "Value", "Base", "Type"):
            table.add_column(column, overflow="fold")
        self.cursor = min(self.cursor, max(len(shown) - 1, 0))
        for index in visible_rows(len(shown), self.cursor, self.page):
            row = shown[index]
            mark = "*" if row.param in self.pending else "●" if row.overridden else " "
            table.add_row(
                mark,
                row.param,
                self._text(row),
                row.base,
                f"{row.kind} {row.hint}".strip(),
                style="reverse" if index == self.cursor else None,
            )
        return Group(Text(heading, style="bold cyan"), table)


def changes_table(rows: Sequence[ParamRow], changes: ParamChanges) -> Table:
    """The changes as ``parameter: current → new`` rows, for confirming them."""
    by_param = {row.param: row for row in rows}
    table = Table(box=None, pad_edge=False, header_style="bold")
    for column in ("Parameter", "Current", "New"):
        table.add_column(column, overflow="fold")
    for param, text in changes.sets:
        table.add_row(param, by_param[param].value, text)
    for param in changes.unsets:
        table.add_row(param, by_param[param].value, f"{by_param[param].base} (reset)")
    return table
