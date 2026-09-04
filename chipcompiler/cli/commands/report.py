from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import report as report_handlers
from chipcompiler.cli.core.inputs import (
    ReportChecklistInput,
    ReportQorInput,
    ReportStepInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import (
    JsonlOption,
    JsonOption,
    PlainOption,
    ProjectOption,
    RunIdOption,
)

report_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help="Generate QoR score and signoff checklist reports",
)

WorkspaceOption = Annotated[
    str | None,
    typer.Option("--workspace", help="Operate on an existing workspace directory"),
]
OutputPathOption = Annotated[
    str | None,
    typer.Option("--output", "-o", help="Report destination (default: <workspace>/signoff/)"),
]


def _finish(subcommand: str, command_input, handler) -> None:
    execute_command("report", command_input, handler, render_key=f"report:{subcommand}")


@report_app.command("qor", help="Overall QoR score report (GUI scoring rules)")
def qor_cmd(
    *,
    output_path: OutputPathOption = None,
    project: ProjectOption = None,
    run_id: RunIdOption = None,
    workspace: WorkspaceOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = ReportQorInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
        project=project_options(project, run_id),
        workspace=workspace,
        output_path=output_path,
    )
    _finish("qor", command_input, report_handlers.qor)


@report_app.command("checklist", help="Signoff checklist status report")
def checklist_cmd(
    *,
    output_path: OutputPathOption = None,
    project: ProjectOption = None,
    run_id: RunIdOption = None,
    workspace: WorkspaceOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = ReportChecklistInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
        project=project_options(project, run_id),
        workspace=workspace,
        output_path=output_path,
    )
    _finish("checklist", command_input, report_handlers.checklist)


SectionOption = Annotated[
    list[str] | None,
    typer.Option(
        "--section",
        help="Limit the detail view to section(s): feature, analysis, checklist",
    ),
]


@report_app.command("step", help="Per-step feature, analysis, and checklist report (read-only)")
def step_cmd(
    *,
    step: Annotated[
        str | None,
        typer.Argument(help="Step token; omit for an overview of all steps"),
    ] = None,
    sections: SectionOption = None,
    project: ProjectOption = None,
    run_id: RunIdOption = None,
    workspace: WorkspaceOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = ReportStepInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
        project=project_options(project, run_id),
        workspace=workspace,
        step=step,
        sections=tuple(sections or ()),
    )
    _finish("step", command_input, report_handlers.step)
