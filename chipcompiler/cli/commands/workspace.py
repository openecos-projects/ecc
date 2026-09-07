"""Commands operating on declared managed workspaces."""

from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import project as project_handlers
from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.inputs import WorkspaceRefreshInput, output_options, project_options
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import JsonlOption, JsonOption, PlainOption, ProjectOption

workspace_app = create_app(help="Refresh managed workspaces from project configuration")


@workspace_app.command("refresh")
def refresh_cmd(
    *,
    workspace: Annotated[str, typer.Argument(help="Declared workspace name")],
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    """Recreate a workspace from ecc.toml without running it.

    Rebuilds the generated configuration from `ecc.toml` and the PDK; manual
    edits to `config/*.json` are overwritten. The workspace hub
    `home/params.toml` keeps four sections: `[design]`, `[pdk]`, `[flow]`,
    and `[params]`. `pdk.*` path changes cannot be applied with
    `ecc param set --workspace`; edit `ecc.toml` and refresh instead.

    See 'ecc doc config' for the full reference.
    """
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
