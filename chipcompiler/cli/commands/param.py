from typing import Annotated

import typer

from chipcompiler.cli.command_handlers.param import param_diff as param_diff_handler
from chipcompiler.cli.command_handlers.param import param_list as param_list_handler
from chipcompiler.cli.command_handlers.param import param_set as param_set_handler
from chipcompiler.cli.command_handlers.param import param_show as param_show_handler
from chipcompiler.cli.command_handlers.param import param_unset as param_unset_handler
from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.inputs import (
    ParamDiffInput,
    ParamListInput,
    ParamSetInput,
    ParamShowInput,
    ParamUnsetInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import CommandHandler, CommandInputT, execute_command
from chipcompiler.cli.core.options import (
    PlainOption,
    ProjectOption,
    WorkspaceOption,
)

param_app = create_app(help="Manage EDA parameters")


def _finish_param(
    param_command: str,
    command_input: CommandInputT,
    handler: CommandHandler[CommandInputT],
) -> None:
    execute_command("param", command_input, handler, render_key=f"param:{param_command}")


@param_app.command("list")
def list_cmd(
    *,
    project: ProjectOption = None,
    step: Annotated[str | None, typer.Option("--step")] = None,
    all_params: Annotated[bool, typer.Option("--all")] = False,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
) -> None:
    """List parameter overrides.

    By default lists the legacy-semantic parameters (such as
    `design.frequency_mhz`, `floorplan.core_util`, `cts.max_fanout`) plus
    direct-config fields that already carry an override. Use `--step STEP` to
    show the full reviewed schema of one step (field, type, and where each
    value is written), or `--all` to show every reviewed field.

    ```bash
    ecc param list --step cts
    ```

    See 'ecc doc config' for the full reference.
    """
    command_input = ParamListInput(
        output=output_options(plain=plain),
        project=project_options(project),
        step=step,
        all=all_params,
        workspace=workspace,
    )
    _finish_param("list", command_input, param_list_handler)


@param_app.command("show")
def show_cmd(
    *,
    key: Annotated[str, typer.Argument()],
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
) -> None:
    """Show one parameter value.

    Reports the current value, default, source, type, and allowed range,
    plus the applicable write targets (`maps_to`, `config_target`,
    `pdk_target`). Some parameters (such as `sta.max_paths`) are passed at
    runtime instead of written to a generated configuration file.

    See 'ecc doc config' for the full reference.
    """
    command_input = ParamShowInput(
        output=output_options(plain=plain),
        project=project_options(project),
        key=key,
        workspace=workspace,
    )
    _finish_param("show", command_input, param_show_handler)


@param_app.command("set", context_settings={"ignore_unknown_options": True})
def set_cmd(
    *,
    key: Annotated[str, typer.Argument()],
    value: Annotated[str, typer.Argument()],
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
) -> None:
    """Set a parameter override.

    Scopes:

    - project (default): the override is written to `ecc.toml`
      (`[params.*]` / `[pdk.overrides]`) and takes effect on the next
      fresh `ecc run`.
    - `--workspace NAME`: written to `home/params.toml` `[params]`;
      the refresh is immediate and the owning step is marked pending.

    Values: scalars are parsed per the reviewed schema type; list and object
    values are JSON literals and arrays replace the previous value wholesale.
    Invalid values fail with `invalid_value` and nothing is written. In the
    workspace scope the owning step and its suffix are marked pending and a
    later `ecc run --workspace NAME` resumes from that step.

    ```bash
    ecc param set cts.skew_bound 0.05
    ecc param set cts.max_buf_tran 0.30
    ecc param set cts.routing_layer '[4, 5]'
    ```

    `pdk.*` path parameters are project-scope only; `pdk.root` is set with
    `ecc pdk set-root`.

    See 'ecc doc config' for the full reference.
    """
    command_input = ParamSetInput(
        output=output_options(plain=plain),
        project=project_options(project),
        key=key,
        value=value,
        workspace=workspace,
    )
    _finish_param("set", command_input, param_set_handler)


@param_app.command("unset")
def unset_cmd(
    *,
    key: Annotated[str, typer.Argument()],
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
) -> None:
    """Remove a parameter override.

    Project scope deletes the key from `ecc.toml`, restoring the default.
    Workspace scope (`--workspace NAME`) restores the pre-edit `baseline` and
    drops the override record; the owning step and its suffix stay invalid
    until they run again.

    See 'ecc doc config' for the full reference.
    """
    command_input = ParamUnsetInput(
        output=output_options(plain=plain),
        project=project_options(project),
        key=key,
        workspace=workspace,
    )
    _finish_param("unset", command_input, param_unset_handler)


@param_app.command("diff")
def diff_cmd(
    *,
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
) -> None:
    """Compare parameter overrides with defaults.

    Project scope lists parameters whose value differs from the default.
    Workspace scope (`--workspace NAME`) lists local overrides together with
    their baselines.

    See 'ecc doc config' for the full reference.
    """
    command_input = ParamDiffInput(
        output=output_options(plain=plain),
        project=project_options(project),
        workspace=workspace,
    )
    _finish_param("diff", command_input, param_diff_handler)
