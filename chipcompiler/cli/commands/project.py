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
    StatusInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import (
    JsonlOption,
    JsonOption,
    PlainOption,
    ProjectOption,
    WorkspaceOption,
)


def register_project_commands(app: typer.Typer) -> None:
    app.command("init", help="Create a new ECC project")(init_cmd)
    app.command("check", help="Validate the current project setup")(check_cmd)
    app.command("run", help="Run the configured RTL-to-GDS flow")(run_cmd)
    app.command(
        "status", help="Show a quick run/step progress summary (full evidence: 'ecc report step')"
    )(status_cmd)
    app.command("log", help="Show available logs or step log content")(log_cmd)
    app.command("config", help="Show resolved project or step configuration")(config_cmd)
    app.command("migrate", help="Migrate a legacy runs/ project to the manifest layout")(
        migrate_cmd
    )


def init_cmd(
    *,
    name: Annotated[str, typer.Argument()],
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = InitInput(
        name=name, output=output_options(json_output=json_output, jsonl=jsonl, plain=plain)
    )
    execute_command("init", command_input, project_handlers.init)


def check_cmd(
    *,
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = CheckInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
        project=project_options(project),
    )
    execute_command("check", command_input, project_handlers.check)


def run_cmd(
    *,
    project: ProjectOption = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", help="Create, select, or resume a managed workspace"),
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
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    param_set: Annotated[
        list[str] | None,
        typer.Option(
            "--set",
            help="Set parameter override (repeatable, e.g. --set place.target_density=0.65)",
        ),
    ] = None,
    plain: PlainOption = False,
) -> None:
    command_input = RunInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
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
    )
    execute_command("run", command_input, project_handlers.run)


def status_cmd(
    *,
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
    workspace: WorkspaceOption = None,
) -> None:
    command_input = StatusInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
        project=project_options(project),
        workspace=workspace,
    )
    execute_command("status", command_input, inspect_handlers.status)


def log_cmd(
    *,
    step: Annotated[str | None, typer.Argument()] = None,
    project: ProjectOption = None,
    json_output: JsonOption = False,
    plain: PlainOption = False,
    jsonl: JsonlOption = False,
    workspace: WorkspaceOption = None,
) -> None:
    command_input = LogInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
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
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = MigrateInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
        project=project_options(project),
        yes=yes,
    )
    execute_command("migrate", command_input, project_handlers.migrate)


def config_cmd(
    *,
    step: Annotated[str | None, typer.Argument()] = None,
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
    workspace: WorkspaceOption = None,
) -> None:
    command_input = ConfigInput(
        output=output_options(json_output=json_output, jsonl=jsonl, plain=plain),
        project=project_options(project),
        step=step,
        workspace=workspace,
    )
    execute_command("config", command_input, inspect_handlers.config)
