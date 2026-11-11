# pyright: strict
"""The rich step table shared by ``ecc flow plan`` and ``ecc flow edit``."""

import sys
from collections.abc import Iterable, Mapping, Sequence
from typing import TextIO

from rich import box
from rich.console import Console, Group, RenderableType
from rich.table import Table
from rich.text import Text

from chipcompiler.cli.project.flow_plan_view import (
    PlanView,
    ProblemSeverity,
    StepRow,
    record_int,
    record_str,
    record_strings,
    view_from_records,
)

_SEVERITY_STYLE: dict[ProblemSeverity, str] = {"error": "bold red", "warning": "yellow"}
_SEVERITY_MARK: dict[ProblemSeverity, str] = {"error": "✖", "warning": "!"}
_UNBOUNDED = 10_000
_LEGEND = "┐…┘ same number = "


def _legend(max_parallel_steps: int) -> str:
    """The stage bracket legend, stating how many steps of a stage run at once."""
    if max_parallel_steps == 1:
        return f"{_LEGEND}independent steps; run one at a time (max_parallel_steps = 1)"
    return f"{_LEGEND}can run in parallel, up to {max_parallel_steps} at once"


def flow_selection_view(
    view: PlanView, *, cursor: int | None = None, footer: str | None = None
) -> RenderableType:
    """The step checklist, its problems and an optional *footer*.

    *cursor* highlights the step at that index (the editor's current row).
    """
    flagged: dict[str, ProblemSeverity] = {}
    for problem in view.problems:
        if flagged.get(problem.step) != "error":
            flagged[problem.step] = problem.severity

    table = Table(
        title=Text(
            f"{view.flow} · {view.enabled_count} of {len(view.steps)} steps enabled",
            style="bold",
        ),
        title_justify="left",
        box=box.SIMPLE_HEAD,
        show_edge=False,
        pad_edge=False,
        collapse_padding=True,
    )
    # After, Gives and the tags wrap between items; none shrinks below its longest
    # item (plus the trailing comma of a list), so a name is never split or cut.
    after_width = _widest_item(_after_names(step) for step in view.steps)
    gives_width = _widest_item(step.provides for step in view.steps)
    tags_width = max((len(tag.plain) for step in view.steps for tag in _tags(step)), default=0)
    label_width = max((len(step.label) for step in view.steps), default=0)
    table.add_column("", no_wrap=True)
    table.add_column("#", no_wrap=True)
    table.add_column("Step", no_wrap=True)
    table.add_column("Tool", no_wrap=True)
    table.add_column("After", min_width=after_width)
    table.add_column("Gives", min_width=gives_width)
    table.add_column("", min_width=tags_width)
    brackets = _brackets(view.steps)
    for index, step in enumerate(view.steps):
        table.add_row(
            *_step_cells(step, label_width, brackets[index], flagged.get(step.step)),
            style=_row_style(step, index, cursor),
        )

    lines: list[RenderableType] = [table]
    if any(step.parallel_with for step in view.steps):
        lines.append(Text(_legend(view.max_parallel_steps), style="dim"))
    lines.extend(
        Text(
            f"{_SEVERITY_MARK[problem.severity]} {problem.severity}: {problem.reason}",
            style=_SEVERITY_STYLE[problem.severity],
        )
        for problem in view.problems
    )
    if not view.problems:
        lines.append(Text("✔ every enabled step has the design data it requires", style="green"))
    if footer:
        lines.append(Text(footer, style="dim"))
    return Group(*lines)


def render_flow_plan_text(
    records: Sequence[Mapping[str, object]], file: TextIO | None = None, *, color: bool = True
) -> None:
    stream = file or sys.stdout
    # force_terminal tracks color: forcing a terminal on a colorless stream
    # makes rich emit ANSI escapes even with no_color=True.
    console = Console(file=stream, force_terminal=color, no_color=not color, highlight=False)
    renderable = flow_selection_view(view_from_records(records))
    if not stream.isatty():
        # Piped output has no terminal width to fit: never truncate or fold a column
        # (measured against an unbounded width, as rich clamps it to the console's).
        # Whether the stream is a terminal is independent of color: a terminal with
        # NO_COLOR or TERM=dumb is colorless but still has a width to wrap within.
        natural = console.measure(renderable, options=console.options.update(width=_UNBOUNDED))
        console.width = max(console.width, natural.maximum)
    console.print(renderable)


def render_flow_edit_text(
    records: Sequence[Mapping[str, object]], file: TextIO | None = None, *, color: bool = True
) -> None:
    """What ``ecc flow edit`` wrote to ecc.toml, then its warnings."""
    console = Console(
        file=file or sys.stdout,
        force_terminal=color,
        no_color=not color,
        highlight=False,
        soft_wrap=True,
    )
    if record_str(records[0], "status") == "cancelled":
        console.print(Text("No changes written.", style="dim"))
        return
    console.print(flow_edit_summary(records, written=True))


def flow_edit_summary(records: Sequence[Mapping[str, object]], *, written: bool) -> RenderableType:
    """The [flow] selection ``ecc flow edit`` wrote (or asks to write), then its warnings."""
    summary = records[0]
    path = record_str(summary, "path")
    lines: list[RenderableType] = [
        Text(f"✔ wrote [flow] to {path}", style="green")
        if written
        else Text(f"Write [flow] to {path}?", style="bold"),
        Text(
            f"  preset = {record_str(summary, 'preset')} · "
            f"lec_engine = {record_str(summary, 'lec_engine')}"
        ),
        Text(f"  skip_steps = {', '.join(record_strings(summary, 'skip_steps'))}"),
        Text(f"  max_parallel_steps = {record_int(summary, 'max_parallel_steps')}"),
    ]
    lines.extend(
        Text(f"  {key}: {', '.join(names)}")
        for key in ("enabled", "disabled")
        if (names := record_strings(summary, key))
    )
    lines.extend(
        Text(f"! warning: {record_str(record, 'reason')}", style="yellow")
        for record in records[1:]
        if record.get("kind") == "warning"
    )
    return Group(*lines)


def _brackets(steps: Sequence[StepRow]) -> list[str]:
    """The stage bracket glyph of every row: ``┐`` ``│`` ``┘`` across a parallel stage.

    A disabled row between the first and last row of a stage keeps the bracket
    continuous.
    """
    span: dict[int, list[int]] = {}
    for index, step in enumerate(steps):
        if step.parallel_with and step.stage is not None:
            span.setdefault(step.stage, []).append(index)
    glyphs = [""] * len(steps)
    for rows in span.values():
        first, last = rows[0], rows[-1]
        glyphs[first] = "┐"
        glyphs[last] = "┘"
        for index in range(first + 1, last):
            glyphs[index] = "│"
    return glyphs


def _widest_item(rows: Iterable[Sequence[str]]) -> int:
    """The longest single item in *rows* plus one for its trailing comma (0 when none)."""
    return max((len(item) + 1 for row in rows for item in row), default=0)


def _after_names(step: StepRow) -> list[str]:
    """The producers of *step*, then its capabilities nothing provides, in parentheses."""
    return [
        *step.after,
        *(f"({capability})" for capability, producer in step.needs if producer is None),
    ]


def _after_cell(step: StepRow) -> Text:
    producers = dict(step.needs)
    required = {producers[capability] for capability in step.requires if capability in producers}
    cell = Text()
    for name in step.after:
        # Optional inputs: the step runs without them, with degraded results.
        _append_item(cell, name, "" if name in required else "italic dim")
    for capability, producer in step.needs:
        if producer is None:
            _append_item(
                cell, f"({capability})", "dim" if capability in step.requires else "italic dim"
            )
    return cell


def _append_item(cell: Text, item: str, style: str) -> None:
    if cell:
        cell.append(", ")
    cell.append(item, style)


def _label_cell(label: str, width: int, bracket: str) -> Text:
    """The stage label padded to *width*, then the dim bracket glyph (none: just the label)."""
    cell = Text(label)
    if bracket:
        cell.append(f"{' ' * (width - len(label) + 1)}")
        cell.append(bracket, "dim")
    return cell


def _tags(step: StepRow) -> list[Text]:
    tags: list[Text] = []
    if step.check:
        tags.append(Text("check"))
    if step.optional:
        tags.append(Text("optional", "italic"))
    if step.target:
        tags.append(Text("target", "cyan"))
    return tags


def _step_cells(
    step: StepRow, label_width: int, bracket: str, severity: ProblemSeverity | None
) -> tuple[Text, ...]:
    name_style = _SEVERITY_STYLE[severity] if severity else "bold" if step.enabled else ""
    return (
        Text("[✔]" if step.enabled else "[ ]", style="green" if step.enabled else "dim"),
        _label_cell(step.label, label_width, bracket),
        Text(step.step, style=name_style),
        Text(step.tool),
        _after_cell(step),
        Text(", ".join(step.provides)),
        Text(" · ").join(_tags(step)),
    )


def _row_style(step: StepRow, index: int, cursor: int | None) -> str:
    if index == cursor:
        return "reverse"
    return "" if step.enabled else "dim"
