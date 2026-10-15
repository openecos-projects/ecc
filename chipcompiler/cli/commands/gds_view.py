from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import gds_view as gds_view_handlers
from chipcompiler.cli.core.inputs import GdsViewInput, output_options, project_options
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import JsonOption, PlainOption, ProjectOption, WorkspaceOption


def register_gds_view_commands(app: typer.Typer) -> None:
    app.command(
        "gdsview",
        help="Open a workspace step's GDS in the KLayout viewer",
    )(gds_view_cmd)


def gds_view_cmd(
    *,
    step: Annotated[str, typer.Option("--step", help="Workspace flow step to open")],
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = GdsViewInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        workspace=workspace,
        step=step,
    )
    execute_command("gdsview", command_input, gds_view_handlers.gds_view)
