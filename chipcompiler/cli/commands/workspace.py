"""Commands operating on declared managed workspaces."""

from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import project as project_handlers
from chipcompiler.cli.core.inputs import WorkspaceRefreshInput, output_options, project_options
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import JsonlOption, JsonOption, PlainOption, ProjectOption

workspace_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help="Refresh managed workspaces from project configuration",
)


@workspace_app.command("refresh", help="Recreate a workspace from ecc.toml without running it")
def refresh_cmd(
    *,
    workspace: Annotated[str, typer.Argument(help="Declared workspace name")],
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = WorkspaceRefreshInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
        project=project_options(project),
        workspace=workspace,
    )
    execute_command(
        "workspace",
        command_input,
        project_handlers.refresh_workspace,
        render_key="workspace:refresh",
    )
