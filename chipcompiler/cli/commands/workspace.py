"""Commands operating on declared managed workspaces."""

from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import project as project_handlers
from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.inputs import (
    WorkspaceArchiveInput,
    WorkspaceCreateInput,
    WorkspaceDeleteInput,
    WorkspaceDeriveInput,
    WorkspaceImportInput,
    WorkspaceReconcileDeletesInput,
    WorkspaceRefreshInput,
    WorkspaceResetFlowInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import PlainOption, ProjectOption

workspace_app = create_app(help="Import or refresh managed workspaces")


@workspace_app.command("reconcile-deletes")
def reconcile_deletes_cmd(
    *,
    project: ProjectOption = None,
    no_wait: Annotated[bool, typer.Option("--no-wait")] = False,
    plain: PlainOption = False,
) -> None:
    command_input = WorkspaceReconcileDeletesInput(
        output=output_options(plain=plain),
        project=project_options(project),
        no_wait=no_wait,
    )
    execute_command("workspace", command_input, project_handlers.reconcile_workspace_deletes)


@workspace_app.command("derive")
def derive_cmd(
    *,
    source_workspace: Annotated[str, typer.Argument(help="Source Workspace ID")],
    target_workspace: Annotated[str, typer.Argument(help="Target Workspace ID")],
    project: ProjectOption = None,
    from_step: Annotated[str | None, typer.Option("--from")] = None,
    command_id: Annotated[str, typer.Option("--command-id")] = "",
    no_wait: Annotated[bool, typer.Option("--no-wait")] = False,
    plain: PlainOption = False,
) -> None:
    command_input = WorkspaceDeriveInput(
        output=output_options(plain=plain),
        project=project_options(project),
        workspace=source_workspace,
        target_workspace=target_workspace,
        from_step=from_step,
        command_id=command_id,
        no_wait=no_wait,
    )
    execute_command("workspace", command_input, project_handlers.derive_workspace)


@workspace_app.command("archive")
def archive_cmd(
    *,
    workspace: Annotated[str, typer.Argument(help="Workspace ID")],
    project: ProjectOption = None,
    expected_revision: Annotated[int | None, typer.Option("--expected-revision", min=1)] = None,
    command_id: Annotated[str, typer.Option("--command-id")] = "",
    no_wait: Annotated[bool, typer.Option("--no-wait")] = False,
    plain: PlainOption = False,
) -> None:
    command_input = WorkspaceArchiveInput(
        output=output_options(plain=plain),
        project=project_options(project),
        workspace=workspace,
        expected_revision=expected_revision,
        command_id=command_id,
        no_wait=no_wait,
    )
    execute_command("workspace", command_input, project_handlers.archive_workspace)


@workspace_app.command("delete")
def delete_cmd(
    *,
    workspace: Annotated[str, typer.Argument(help="Workspace ID")],
    project: ProjectOption = None,
    expected_revision: Annotated[int | None, typer.Option("--expected-revision", min=1)] = None,
    command_id: Annotated[str, typer.Option("--command-id")] = "",
    no_wait: Annotated[bool, typer.Option("--no-wait")] = False,
    delete_directory: Annotated[bool, typer.Option("--delete-directory")] = False,
    plain: PlainOption = False,
) -> None:
    command_input = WorkspaceDeleteInput(
        output=output_options(plain=plain),
        project=project_options(project),
        workspace=workspace,
        expected_revision=expected_revision,
        command_id=command_id,
        no_wait=no_wait,
        delete_directory=delete_directory,
    )
    execute_command("workspace", command_input, project_handlers.delete_workspace)


@workspace_app.command("reset-flow")
def reset_flow_cmd(
    *,
    workspace: Annotated[str, typer.Argument(help="Workspace ID")],
    project: ProjectOption = None,
    expected_revision: Annotated[int | None, typer.Option("--expected-revision", min=1)] = None,
    command_id: Annotated[str, typer.Option("--command-id")] = "",
    no_wait: Annotated[bool, typer.Option("--no-wait")] = False,
    plain: PlainOption = False,
) -> None:
    command_input = WorkspaceResetFlowInput(
        output=output_options(plain=plain),
        project=project_options(project),
        workspace=workspace,
        expected_revision=expected_revision,
        command_id=command_id,
        no_wait=no_wait,
    )
    execute_command("workspace", command_input, project_handlers.reset_workspace_flow)


@workspace_app.command("create")
def create_cmd(
    *,
    workspace: Annotated[str, typer.Argument(help="Workspace ID to create")],
    project: ProjectOption = None,
    path: Annotated[str | None, typer.Option("--path")] = None,
    from_step: Annotated[str | None, typer.Option("--from")] = None,
    to_step: Annotated[str | None, typer.Option("--to")] = None,
    param_set: Annotated[list[str] | None, typer.Option("--set")] = None,
    command_id: Annotated[str, typer.Option("--command-id")] = "",
    no_wait: Annotated[bool, typer.Option("--no-wait")] = False,
    plain: PlainOption = False,
) -> None:
    command_input = WorkspaceCreateInput(
        output=output_options(plain=plain),
        project=project_options(project),
        workspace=workspace,
        path=path,
        from_step=from_step,
        to_step=to_step,
        param_set=tuple(param_set or ()),
        command_id=command_id,
        no_wait=no_wait,
    )
    execute_command("workspace", command_input, project_handlers.create_workspace)


@workspace_app.command("import")
def import_cmd(
    *,
    workspace: Annotated[str, typer.Argument(help="Workspace ID to register")],
    path: Annotated[
        str,
        typer.Option("--path", help="Exact absolute directory of an existing workspace"),
    ],
    project: ProjectOption = None,
    no_wait: Annotated[bool, typer.Option("--no-wait")] = False,
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
        no_wait=no_wait,
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
    keep_backup: Annotated[
        bool,
        typer.Option(
            "--keep-backup",
            help="Keep the replaced workspace as an archived .replace-backup-* directory",
        ),
    ] = False,
    project: ProjectOption = None,
    expected_revision: Annotated[int | None, typer.Option("--expected-revision", min=1)] = None,
    command_id: Annotated[str, typer.Option("--command-id")] = "",
    no_wait: Annotated[bool, typer.Option("--no-wait")] = False,
    plain: PlainOption = False,
) -> None:
    """Recreate a workspace from ecc.toml without running it.

    Rebuilds the generated configuration from `ecc.toml` and the PDK; manual
    edits to `config/*.json` are overwritten. When a change since the last
    derivation is detected, refresh refuses and lists the modified files
    unless --force is given. The workspace hub `home/params.toml` keeps four
    sections: `[design]`, `[pdk]`, `[flow]`, and `[params]`. `pdk.*` path
    changes cannot be applied with `ecc param set --workspace`; edit
    `ecc.toml` and refresh instead. With --keep-backup the replaced tree is
    kept as a sibling `.<name>.replace-backup-<N>` directory and registered
    in `project.json` as an archived workspace.

    See 'ecc doc config' for the full reference.
    """
    command_input = WorkspaceRefreshInput(
        output=output_options(plain=plain),
        project=project_options(project),
        workspace=workspace,
        force=force,
        expected_revision=expected_revision,
        command_id=command_id,
        no_wait=no_wait,
    )
    execute_command(
        "workspace",
        command_input,
        project_handlers.refresh_workspace,
        render_key="workspace:refresh",
    )
