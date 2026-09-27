from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import signoff as signoff_handlers
from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.inputs import (
    SignoffExportInput,
    SignoffInspectInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import (
    PlainOption,
    ProjectOption,
    WorkspaceOption,
)

signoff_app = create_app(help="Inspect and export signoff packages")


def _finish(subcommand: str, command_input, handler) -> None:
    execute_command("signoff", command_input, handler, render_key=f"signoff:{subcommand}")


@signoff_app.command("inspect", help="Review signoff package readiness")
def inspect_cmd(
    *,
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
) -> None:
    command_input = SignoffInspectInput(
        output=output_options(plain=plain),
        project=project_options(project),
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
    expected_revision: Annotated[int | None, typer.Option("--expected-revision", min=1)] = None,
    no_wait: Annotated[bool, typer.Option("--no-wait")] = False,
    additional_files: Annotated[str | None, typer.Option("--additional-files")] = None,
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
) -> None:
    command_input = SignoffExportInput(
        output=output_options(plain=plain),
        project=project_options(project),
        workspace=workspace,
        output_path=output_path,
        include_debug=include_debug,
        expected_revision=expected_revision,
        no_wait=no_wait,
        additional_files=additional_files,
    )
    _finish("export", command_input, signoff_handlers.export)
