from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import signoff as signoff_handlers
from chipcompiler.cli.core.inputs import (
    SignoffExportInput,
    SignoffInspectInput,
    SignoffReportInput,
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

signoff_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help="Inspect and export signoff packages",
)

WorkspaceOption = Annotated[
    str | None,
    typer.Option("--workspace", help="Operate on an existing workspace directory"),
]


def _finish(subcommand: str, command_input, handler) -> None:
    execute_command("signoff", command_input, handler, render_key=f"signoff:{subcommand}")


@signoff_app.command("inspect", help="Review signoff package readiness")
def inspect_cmd(
    *,
    project: ProjectOption = None,
    run_id: RunIdOption = None,
    workspace: WorkspaceOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = SignoffInspectInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
        project=project_options(project, run_id),
        workspace=workspace,
    )
    _finish("inspect", command_input, signoff_handlers.inspect)


@signoff_app.command("export", help="Export the signoff package as a tar.gz archive")
def export_cmd(
    *,
    output_path: Annotated[str, typer.Option("--output", "-o", help="Archive destination path")],
    include_debug: Annotated[
        bool,
        typer.Option("--include-debug", help="Include debug artifacts in the package"),
    ] = False,
    project: ProjectOption = None,
    run_id: RunIdOption = None,
    workspace: WorkspaceOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = SignoffExportInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
        project=project_options(project, run_id),
        workspace=workspace,
        output_path=output_path,
        include_debug=include_debug,
    )
    _finish("export", command_input, signoff_handlers.export)


@signoff_app.command("report", help="Write the text design summary report")
def report_cmd(
    *,
    output_path: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Report destination (default: <workspace>/signoff/)"),
    ] = None,
    project: ProjectOption = None,
    run_id: RunIdOption = None,
    workspace: WorkspaceOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = SignoffReportInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
        project=project_options(project, run_id),
        workspace=workspace,
        output_path=output_path,
    )
    _finish("report", command_input, signoff_handlers.report)
