from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import report as report_handlers
from chipcompiler.cli.command_handlers import report_project as project_handlers
from chipcompiler.cli.command_handlers import report_snapshot as snapshot_handlers
from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.inputs import (
    ReportChecklistInput,
    ReportQorInput,
    ReportStepInput,
    ReportSummaryInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import (
    JsonOption,
    PlainOption,
    ProjectOption,
    WorkspaceOption,
)
from chipcompiler.cli.core.project_report_inputs import ReportProjectInput
from chipcompiler.cli.core.snapshot_inputs import ReportSnapshotInput

report_app = create_app(
    help="Generate design-summary, QoR score, checklist, step reports, and saved snapshots"
)

OutputPathOption = Annotated[
    str | None,
    typer.Option("--output", "-o", help="Report destination (default: `<workspace>`/signoff/)"),
]


def _finish(subcommand: str, command_input, handler) -> None:
    execute_command("report", command_input, handler, render_key=f"report:{subcommand}")


@report_app.command(
    "project", help="Rank all declared workspaces by saved QoR and show step/checker states"
)
def project_cmd(
    *,
    project: ProjectOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = ReportProjectInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
    )
    _finish("project", command_input, project_handlers.project)


@report_app.command("snapshot", help="Save the committed Engineering Snapshot without running EDA")
def snapshot_cmd(
    *,
    output_path: Annotated[
        str, typer.Option("--output", "-o", help="New JSON file outside the source workspace")
    ],
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = ReportSnapshotInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        workspace=workspace,
        output_path=output_path,
    )
    _finish("snapshot", command_input, snapshot_handlers.snapshot)


@report_app.command("qor", help="Show the overall QoR score report")
def qor_cmd(
    *,
    output_path: OutputPathOption = None,
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = ReportQorInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        workspace=workspace,
        output_path=output_path,
    )
    _finish("qor", command_input, report_handlers.qor)


@report_app.command("checklist", help="Show the signoff checklist status report")
def checklist_cmd(
    *,
    output_path: OutputPathOption = None,
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = ReportChecklistInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        workspace=workspace,
        output_path=output_path,
    )
    _finish("checklist", command_input, report_handlers.checklist)


@report_app.command("summary", help="Write the text design summary report")
def summary_cmd(
    *,
    output_path: OutputPathOption = None,
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = ReportSummaryInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        workspace=workspace,
        output_path=output_path,
    )
    _finish("summary", command_input, report_handlers.summary)


SectionOption = Annotated[
    list[str] | None,
    typer.Option(
        "--section",
        help="Limit the detail view to section(s): feature, analysis, checklist, outputs",
    ),
]


@report_app.command(
    "step",
    help="Show the full per-step evidence report (features, analysis, checklist); "
    "for a quick progress check use 'ecc status'",
)
def step_cmd(
    *,
    step: Annotated[
        str | None,
        typer.Argument(help="Step token; omit for an overview of all steps"),
    ] = None,
    sections: SectionOption = None,
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = ReportStepInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        workspace=workspace,
        step=step,
        sections=tuple(sections or ()),
    )
    _finish("step", command_input, report_handlers.step)
