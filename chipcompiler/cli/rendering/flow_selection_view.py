# pyright: strict
"""The rich step table shared by ``ecc flow plan`` and ``ecc flow edit``."""

import sys
from collections.abc import Mapping, Sequence
from typing import TextIO

from rich import box
from rich.console import Console, Group, RenderableType
from rich.table import Table
from rich.text import Text

from chipcompiler.cli.project.flow_plan_view import (
    PlanView,
    ProblemSeverity,
    StepRow,
    record_str,
    record_strings,
    view_from_records,
)

_SEVERITY_STYLE: dict[ProblemSeverity, str] = {"error": "bold red", "warning": "yellow"}
_SEVERITY_MARK: dict[ProblemSeverity, str] = {"error": "✖", "warning": "!"}
_COLUMNS = (
    ("", "left"),
    ("#", "right"),
    ("Step", "left"),
    ("Tool", "left"),
    ("Needs", "left"),
    ("Gives", "left"),
    ("", "left"),
)


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
    )
    for header, justify in _COLUMNS:
        table.add_column(
            header, justify="right" if justify == "right" else "left", no_wrap=header != "Needs"
        )
    for index, step in enumerate(view.steps):
        table.add_row(
            *_step_cells(step, flagged.get(step.step)), style=_row_style(step, index, cursor)
        )

    lines: list[RenderableType] = [table]
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
    # force_terminal tracks color: forcing a terminal on a colorless stream
    # makes rich emit ANSI escapes even with no_color=True.
    console = Console(
        file=file or sys.stdout, force_terminal=color, no_color=not color, highlight=False
    )
    console.print(flow_selection_view(view_from_records(records)))


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


def _step_cells(step: StepRow, severity: ProblemSeverity | None) -> tuple[Text, ...]:
    needs = Text(", ".join(step.requires))
    if step.uses:
        # Optional inputs: the step runs without them, with degraded results.
        needs.append((", " if step.requires else "") + ", ".join(step.uses), "italic dim")
    tags = Text()
    if step.optional:
        tags.append("optional", "italic")
    if step.target:
        tags.append("target", "cyan")
    name_style = _SEVERITY_STYLE[severity] if severity else "bold" if step.enabled else ""
    return (
        Text("[✔]" if step.enabled else "[ ]", style="green" if step.enabled else "dim"),
        Text(str(step.position)),
        Text(step.step, style=name_style),
        Text(step.tool),
        needs,
        Text(", ".join(step.provides)),
        tags,
    )


def _row_style(step: StepRow, index: int, cursor: int | None) -> str:
    if index == cursor:
        return "reverse"
    return "" if step.enabled else "dim"
