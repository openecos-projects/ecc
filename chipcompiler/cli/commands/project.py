from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import inspect as inspect_handlers
from chipcompiler.cli.command_handlers import project as project_handlers
from chipcompiler.cli.core.inputs import (
    CheckInput,
    ConfigInput,
    InitInput,
    LogInput,
    MigrateInput,
    RunInput,
    RtlImportInput,
    StatusInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import (
    PlainOption,
    ProjectOption,
    WorkspaceOption,
)


def register_project_commands(app: typer.Typer) -> None:
    app.command("init", help="Create a new ECC project")(init_cmd)
    app.add_typer(rtl_app, name="rtl")
    app.command("check", help="Validate the current project setup")(check_cmd)
    app.command("run")(run_cmd)
    app.command(
        "status", help="Show a quick run/step progress summary (full evidence: 'ecc report step')"
    )(status_cmd)
    app.command("log", help="Show available logs or step log content")(log_cmd)
    app.command("config")(config_cmd)
    app.command("migrate", help="Migrate a legacy runs/ project to the manifest layout")(
        migrate_cmd
    )


rtl_app = typer.Typer(help="Import project RTL sources")


@rtl_app.command("import")
def rtl_import_cmd(
    *,
    filelist: Annotated[str | None, typer.Option("--filelist")] = None,
    verilog: Annotated[list[str] | None, typer.Option("--verilog")] = None,
    project: ProjectOption = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    plain: PlainOption = False,
) -> None:
    if not filelist and not verilog:
        raise typer.BadParameter("provide --filelist or at least one --verilog")
    command_input = RtlImportInput(
        output=output_options(plain=plain),
        project=project_options(project),
        filelist=filelist,
        verilog=tuple(verilog or ()),
        force=force,
    )
    execute_command("project", command_input, project_handlers.import_rtl)


def init_cmd(
    *,
    name: Annotated[str, typer.Argument()],
    project_name: Annotated[str | None, typer.Option("--project-name")] = None,
    design_name: Annotated[str | None, typer.Option("--design-name")] = None,
    mpc_resource_id: Annotated[str | None, typer.Option("--mpc-resource-id")] = None,
    mpc_display_name: Annotated[str | None, typer.Option("--mpc-display-name")] = None,
    mpc_version: Annotated[str | None, typer.Option("--mpc-version")] = None,
    mpc_root: Annotated[str | None, typer.Option("--mpc-root")] = None,
    mpc_design_index: Annotated[int | None, typer.Option("--mpc-design-index", min=0)] = None,
    plain: PlainOption = False,
) -> None:
    command_input = InitInput(
        name=name,
        output=output_options(plain=plain),
        project_name=project_name,
        design_name=design_name,
        mpc_resource_id=mpc_resource_id,
        mpc_display_name=mpc_display_name,
        mpc_version=mpc_version,
        mpc_root=mpc_root,
        mpc_design_index=mpc_design_index,
    )
    execute_command("init", command_input, project_handlers.init)


def check_cmd(
    *,
    project: ProjectOption = None,
    plain: PlainOption = False,
    workspace: WorkspaceOption = None,
) -> None:
    command_input = CheckInput(
        output=output_options(plain=plain),
        project=project_options(project),
        workspace=workspace,
    )
    execute_command("check", command_input, project_handlers.check)


def run_cmd(
    *,
    project: ProjectOption = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
    workspace: Annotated[
        str | None,
        typer.Option(
            "--workspace",
            help="Create, select, or resume a workspace name or absolute path",
        ),
    ] = None,
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Continue from the first non-successful step"),
    ] = False,
    from_step: Annotated[
        str | None,
        typer.Option("--from", help="Re-execute a step and its persisted suffix"),
    ] = None,
    to_step: Annotated[
        str | None,
        typer.Option("--to", help="Inclusive final step when running a bounded range"),
    ] = None,
    only: Annotated[
        str | None,
        typer.Option("--only", help="Run exactly one persisted step"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-execute an already successful --only step"),
    ] = False,
    preset: Annotated[
        str | None,
        typer.Option(
            "--preset",
            help="Flow preset for this run only, e.g. --preset syn_sta (does not edit ecc.toml)",
        ),
    ] = None,
    param_set: Annotated[
        list[str] | None,
        typer.Option(
            "--set",
            help="Set parameter override (repeatable, e.g. --set place.target_density=0.65)",
        ),
    ] = None,
    expected_revision: Annotated[int | None, typer.Option("--expected-revision", min=1)] = None,
    command_id: Annotated[str, typer.Option("--command-id")] = "",
    no_wait: Annotated[bool, typer.Option("--no-wait")] = False,
    run_id: Annotated[str, typer.Option("--run-id")] = "",
    runtime_id: Annotated[str, typer.Option("--runtime-id")] = "",
    log_file: Annotated[str, typer.Option("--log-file")] = "",
    plain: PlainOption = False,
) -> None:
    """Run the configured RTL-to-GDS flow.

    `--set KEY=VALUE` applies a one-off parameter override; it is accepted
    only when the run creates a workspace (including `--overwrite`) and is
    recorded in `home/cli-param-overrides.json`. On an existing workspace it
    fails with `set_requires_fresh_run` — use
    `ecc param set KEY VALUE --workspace NAME` instead. Precedence:
    `--set` > `ecc.toml` `[params]` > defaults.

    Parameterized fields in `config/*.json` are re-refreshed from
    `home/params.toml` and the PDK before every step, so manual edits are
    overwritten. Each step reads the previous step's `output/`; the first
    step reads the design's origin verilog/DEF.

    See 'ecc doc config' for the full reference.
    """
    command_input = RunInput(
        output=output_options(plain=plain),
        project=project_options(project),
        overwrite=overwrite,
        param_set=tuple(param_set or ()),
        workspace=workspace,
        resume=resume,
        from_step=from_step,
        to_step=to_step,
        only=only,
        force=force,
        preset=preset,
        expected_revision=expected_revision,
        command_id=command_id,
        no_wait=no_wait,
        run_id=run_id,
        runtime_id=runtime_id,
        log_file=log_file,
    )
    execute_command("run", command_input, project_handlers.run)


def status_cmd(
    *,
    project: ProjectOption = None,
    plain: PlainOption = False,
    workspace: WorkspaceOption = None,
) -> None:
    command_input = StatusInput(
        output=output_options(plain=plain),
        project=project_options(project),
        workspace=workspace,
    )
    execute_command("status", command_input, inspect_handlers.status)


def log_cmd(
    *,
    step: Annotated[str | None, typer.Argument()] = None,
    project: ProjectOption = None,
    plain: PlainOption = False,
    workspace: WorkspaceOption = None,
) -> None:
    command_input = LogInput(
        output=output_options(plain=plain),
        project=project_options(project),
        step=step,
        workspace=workspace,
    )
    execute_command("log", command_input, inspect_handlers.log)


def migrate_cmd(
    *,
    project: ProjectOption = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Migrate without interactive confirmation"),
    ] = False,
    plain: PlainOption = False,
) -> None:
    command_input = MigrateInput(
        output=output_options(plain=plain),
        project=project_options(project),
        yes=yes,
    )
    execute_command("migrate", command_input, project_handlers.migrate)


def config_cmd(
    *,
    step: Annotated[str | None, typer.Argument()] = None,
    project: ProjectOption = None,
    plain: PlainOption = False,
    workspace: WorkspaceOption = None,
) -> None:
    """Show resolved project or step configuration.

    Without STEP: resolved project-level configuration. With STEP: the
    configuration files actually in effect for that step. `lec`, `lvs`,
    `postroutelec`, and `harden` have no step-specific configuration
    (Tcl-driven, tool-default, or reusing `db_ecc.json`).

    See 'ecc doc config' for the full reference.
    """
    command_input = ConfigInput(
        output=output_options(plain=plain),
        project=project_options(project),
        step=step,
        workspace=workspace,
    )
    execute_command("config", command_input, inspect_handlers.config)
