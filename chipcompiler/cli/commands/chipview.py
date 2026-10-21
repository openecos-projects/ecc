from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import chipview as chipview_handlers
from chipcompiler.cli.core.inputs import ChipviewInput, output_options, project_options
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import JsonOption, PlainOption, ProjectOption, WorkspaceOption


def register_chipview_commands(app: typer.Typer) -> None:
    app.command(
        "chipview",
        help="Open a workspace step's saved geometry snapshot in Chip Viewer",
    )(chipview_cmd)


def chipview_cmd(
    *,
    step: Annotated[str, typer.Option("--step", help="Workspace flow step to open")],
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = ChipviewInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        workspace=workspace,
        step=step,
    )
    execute_command("chipview", command_input, chipview_handlers.chipview)
