# pyright: strict
"""The ``ecc workspace fork`` picker: source workspace, restart step, name, confirmation.

Each screen is one step back from the next (esc). The restart step keeps the
steps before it with their results and reruns it and the steps after it;
``t`` also picks the last step to build (``--to``). The summary forks on
``y``, or on ``e`` forks and then opens the parameter editor on the new
workspace.
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
    KeyReader,
    TextField,
    moved,
    next_key,
    visible_rows,
)

#: The error that keeps a name from naming the new workspace, or None.
NameCheck = Callable[[str], str | None]

_SOURCE_KEYS = "↑/↓ move · enter fork this workspace · q cancel"
_FROM_KEYS = "↑/↓ move · enter rerun from here · t also choose the last step · esc back · q cancel"
_TO_KEYS = "↑/↓ move · enter build up to here · esc back · q cancel"
_NAME_KEYS = "enter accept · esc back"
_CONFIRM_KEYS = "y fork · e fork and edit its parameters · esc back · n/q cancel"
_END = frozenset({"t"})
_YES = frozenset({"y", "Y"})
_EDIT = frozenset({"e", "E"})
_NO = frozenset({"n", "N"})
#: Lines the title, header and footer take around the rows.
_CHROME = 8


@dataclass(frozen=True, slots=True)
class SourceRow:
    """A workspace of the project; *blocked* says why it cannot be forked (None: it can)."""

    workspace_id: str
    status: str
    done: int
    total: int
    forked_from: str = ""
    blocked: str | None = None


@dataclass(frozen=True, slots=True)
class StepRow:
    """A step of the source workspace's flow and its state there."""

    name: str
    state: str


@dataclass(frozen=True, slots=True)
class ForkChoice:
    """What to fork: ``--from`` *from_step* (``--to`` *to_step*) into *target*."""

    source: str
    from_step: str
    to_step: str | None
    target: str
    edit_parameters: bool

    def rerun_steps(self, steps: Sequence[StepRow]) -> list[str]:
        """The steps of *steps* the fork reruns."""
        names = [step.name for step in steps]
        end = names.index(self.to_step) if self.to_step else len(names) - 1
        return names[names.index(self.from_step) : end + 1]


def choose_fork(
    sources: Sequence[SourceRow],
    steps_of: Callable[[str], Sequence[StepRow]],
    *,
    source: str | None,
    target: str | None,
    suggest_name: Callable[[str], str],
    check_name: NameCheck,
    console: Console,
    read_key: KeyReader,
) -> ForkChoice | None:
    """Ask for what the fork lacks, then confirm it (the choice) or cancel (None).

    A given *source* skips its screen and a given *target* the name screen.
    A source with no steps is refused before (a given one) or on its screen
    (*sources* marks it ``blocked``).
    """
    page = max(console.height - _CHROME, 3)
    picker = _Picker(sources, steps_of, source, target, suggest_name, check_name, page)
    pending: list[str] = []
    with Live(picker.render(), console=console, auto_refresh=False, transient=True) as live:
        while True:
            try:
                key = next_key(pending, read_key)
            except (KeyboardInterrupt, EOFError):
                return None
            outcome = picker.press(key)
            if isinstance(outcome, ForkChoice):
                return outcome
            if outcome is False:
                return None
            live.update(picker.render(), refresh=True)


class _Picker:
    def __init__(
        self,
        sources: Sequence[SourceRow],
        steps_of: Callable[[str], Sequence[StepRow]],
        source: str | None,
        target: str | None,
        suggest_name: Callable[[str], str],
        check_name: NameCheck,
        page: int,
    ) -> None:
        self.sources = list(sources)
        self.steps_of = steps_of
        self.given_source = source
        self.given_target = target
        self.suggest_name = suggest_name
        self.check_name = check_name
        self.page = page
        self.source = source
        self.steps: list[StepRow] = list(steps_of(source)) if source else []
        self.screen = "from" if source else "source"
        self.cursor = 0
        self.from_index = 0
        self.to_index: int | None = None
        self.name = TextField()
        self.notice = ""

    # -- keys ---------------------------------------------------------------

    def press(self, key: str) -> "ForkChoice | bool | None":
        """The choice, False to cancel, or None to go on."""
        self.notice = ""
        if self.screen == "name":
            return self._press_name(key)
        if key in CANCEL and key != ESCAPE:
            return False
        if key == ESCAPE:
            return self._back()
        if self.screen == "confirm":
            return self._press_confirm(key)
        rows = len(self.sources) if self.screen == "source" else len(self.steps)
        if rows and (cursor := moved(self.cursor, key, rows, self.page)) is not None:
            if self.screen == "to":
                cursor = max(cursor, self.from_index)
            self.cursor = cursor
        elif self.screen == "source" and key in ENTER:
            self._choose_source()
        elif self.screen == "from" and (key in ENTER or key in _END):
            self.from_index = self.cursor
            if key in _END:
                self.screen, self.cursor = "to", len(self.steps) - 1
            else:
                self.to_index = None
                self._to_name()
        elif self.screen == "to" and key in ENTER:
            self.to_index = self.cursor if self.cursor < len(self.steps) - 1 else None
            self._to_name()
        return None

    def _choose_source(self) -> None:
        if not self.sources:
            return
        row = self.sources[self.cursor]
        if row.blocked is not None:
            self.notice = f"{row.workspace_id} cannot be forked: {row.blocked}"
            return
        self.source, self.steps = row.workspace_id, list(self.steps_of(row.workspace_id))
        self.screen, self.cursor = "from", 0

    def _to_name(self) -> None:
        if self.given_target is not None:
            self.screen = "confirm"
            return
        assert self.source is not None
        if not self.name.text:
            self.name.text = self.suggest_name(self.source)
        self.screen = "name"

    def _press_name(self, key: str) -> None:
        if key == ESCAPE or key in {"\x03", "\x04"}:
            self._back()
        elif key in ENTER:
            error = self.check_name(self.name.text)
            if error:
                self.notice = error
            else:
                self.screen = "confirm"
        else:
            self.name.feed(key)

    def _press_confirm(self, key: str) -> "ForkChoice | bool | None":
        if key in _YES or key in _EDIT:
            assert self.source is not None
            return ForkChoice(
                source=self.source,
                from_step=self.steps[self.from_index].name,
                to_step=None if self.to_index is None else self.steps[self.to_index].name,
                target=self.given_target or self.name.text,
                edit_parameters=key in _EDIT,
            )
        if key in _NO or key in ENTER:
            return False
        return None

    def _back(self) -> "bool | None":
        """One screen back; from the first screen, cancel (False)."""
        if self.screen == "confirm":
            self.screen = "name" if self.given_target is None else "from"
            if self.screen == "from":
                self.cursor = self.from_index
        elif self.screen == "name" or self.screen == "to":
            self.screen, self.cursor = "from", self.from_index
        elif self.screen == "from" and self.given_source is None:
            self.screen = "source"
            self.cursor = next(
                (i for i, row in enumerate(self.sources) if row.workspace_id == self.source), 0
            )
        else:
            return False
        return None

    # -- drawing ------------------------------------------------------------

    def render(self) -> RenderableType:
        if self.screen == "source":
            parts: list[RenderableType] = [
                Text("Fork which workspace?", style="bold"),
                self._source_table(),
            ]
            keys = _SOURCE_KEYS
        elif self.screen in {"from", "to"}:
            question = (
                f"Rerun {self.source} from which step?"
                if self.screen == "from"
                else f"Build {self.source} up to which step?"
            )
            parts = [Text(question, style="bold"), self._step_table()]
            keys = _FROM_KEYS if self.screen == "from" else _TO_KEYS
        elif self.screen == "name":
            parts = [
                Text("Name the new workspace", style="bold"),
                self._step_table(),
                Text(f"name> {self.name.text}▏", style="bold"),
            ]
            keys = _NAME_KEYS
        else:
            parts = [Text(self._summary(), style="bold"), self._step_table()]
            keys = _CONFIRM_KEYS
        if self.notice:
            parts.append(Text(self.notice, style="red"))
        parts.append(Text(keys, style="dim"))
        return Group(*parts)

    def _summary(self) -> str:
        target = self.given_target or self.name.text
        start = self.steps[self.from_index].name
        end = self.steps[self.to_index].name if self.to_index is not None else self.steps[-1].name
        return f"Fork {self.source} into {target}, rerunning {start}..{end}"

    def _source_table(self) -> Table:
        table = Table(box=None, pad_edge=False, header_style="bold")
        for column in ("", "Workspace", "Status", "Steps done", "Forked from", ""):
            table.add_column(column)
        for index in visible_rows(len(self.sources), self.cursor, self.page):
            row = self.sources[index]
            table.add_row(
                "›" if index == self.cursor else " ",
                row.workspace_id,
                row.status,
                f"{row.done}/{row.total}",
                row.forked_from,
                row.blocked or "",
                style="reverse"
                if index == self.cursor
                else "dim"
                if row.blocked is not None
                else None,
            )
        return table

    def _step_table(self) -> Table:
        table = Table(box=None, pad_edge=False, header_style="bold")
        for column in ("", "Step", "State", "In the fork"):
            table.add_column(column)
        choosing = self.screen in {"from", "to"}
        start = self.cursor if self.screen == "from" else self.from_index
        end = self.cursor if self.screen == "to" else self.to_index
        if end is None:
            end = len(self.steps) - 1
        for index in visible_rows(len(self.steps), self.cursor if choosing else start, self.page):
            step = self.steps[index]
            role = "keep" if index < start else "rerun" if index <= end else "not built"
            table.add_row(
                "›" if choosing and index == self.cursor else " ",
                step.name,
                step.state,
                role,
                style="reverse"
                if choosing and index == self.cursor
                else "green"
                if role == "keep"
                else "dim"
                if role == "not built"
                else None,
            )
        return table
