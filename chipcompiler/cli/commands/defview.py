from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import defview as defview_handlers
from chipcompiler.cli.core.inputs import DefviewInput, output_options, project_options
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import JsonOption, PlainOption, ProjectOption, WorkspaceOption


def register_defview_command(app: typer.Typer) -> None:
    app.command(
        "defview",
        help="Generate geometry from a DEF using the selected Workspace's LEF and parameters",
    )(defview_cmd)


def defview_cmd(
    *,
    def_path: Annotated[
        str,
        typer.Option("--def", help="DEF or DEF.GZ layout to load into the Workspace"),
    ],
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = DefviewInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        workspace=workspace,
        def_path=def_path,
    )
    execute_command("defview", command_input, defview_handlers.defview)
