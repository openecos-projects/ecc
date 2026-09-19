"""Commands operating on declared managed workspaces."""

from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import project as project_handlers
from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.inputs import (
    WorkspaceImportInput,
    WorkspaceRefreshInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import PlainOption, ProjectOption

workspace_app = create_app(help="Import or refresh managed workspaces")


@workspace_app.command("import")
def import_cmd(
    *,
    workspace: Annotated[str, typer.Argument(help="Workspace ID to register")],
    path: Annotated[
        str,
        typer.Option("--path", help="Exact absolute directory of an existing workspace"),
    ],
    project: ProjectOption = None,
    plain: PlainOption = False,
) -> None:
    """Register an existing workspace without changing or running it.

    The workspace remains at its current directory. Future commands select it
    by WORKSPACE through the owning project's `project.json`.
    """
    command_input = WorkspaceImportInput(
        output=output_options(plain=plain),
        project=project_options(project),
        workspace=workspace,
        path=path,
    )
    execute_command("workspace", command_input, project_handlers.import_workspace)


@workspace_app.command("refresh")
def refresh_cmd(
    *,
    workspace: Annotated[str, typer.Argument(help="Declared workspace name")],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite hand-edited config/*.json without asking",
        ),
    ] = False,
    project: ProjectOption = None,
    plain: PlainOption = False,
) -> None:
    """Recreate a workspace from ecc.toml without running it.

    Rebuilds the generated configuration from `ecc.toml` and the PDK; manual
    edits to `config/*.json` are overwritten. When a change since the last
    derivation is detected, refresh refuses and lists the modified files
    unless --force is given. The workspace hub `home/params.toml` keeps four
    sections: `[design]`, `[pdk]`, `[flow]`, and `[params]`. `pdk.*` path
    changes cannot be applied with `ecc param set --workspace`; edit
    `ecc.toml` and refresh instead.

    See 'ecc doc config' for the full reference.
    """
    command_input = WorkspaceRefreshInput(
        output=output_options(plain=plain),
        project=project_options(project),
        workspace=workspace,
        force=force,
    )
    execute_command(
        "workspace",
        command_input,
        project_handlers.refresh_workspace,
        render_key="workspace:refresh",
    )
