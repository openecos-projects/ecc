"""Commands for detached ECC run process control."""

from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import process as process_handlers
from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.inputs import (
    ProcessCancelInput,
    ProcessInspectInput,
    ProcessReconcileInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import PlainOption, ProjectOption

process_app = create_app(help="Inspect, cancel, or reconcile ECC run processes")


@process_app.command("inspect")
def inspect_cmd(
    *,
    workspace: Annotated[str, typer.Option("--workspace")],
    project: ProjectOption = None,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    plain: PlainOption = False,
) -> None:
    execute_command(
        "process",
        ProcessInspectInput(
            output=output_options(plain=plain),
            project=project_options(project),
            workspace=workspace,
            run_id=run_id,
        ),
        process_handlers.inspect_process,
    )


@process_app.command("cancel")
def cancel_cmd(
    *,
    workspace: Annotated[str, typer.Option("--workspace")],
    run_id: Annotated[str, typer.Option("--run-id")],
    project: ProjectOption = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    plain: PlainOption = False,
) -> None:
    execute_command(
        "process",
        ProcessCancelInput(
            output=output_options(plain=plain),
            project=project_options(project),
            workspace=workspace,
            run_id=run_id,
            force=force,
        ),
        process_handlers.cancel_process,
    )


@process_app.command("reconcile")
def reconcile_cmd(
    *,
    workspace: Annotated[str, typer.Option("--workspace")],
    project: ProjectOption = None,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    no_wait: Annotated[bool, typer.Option("--no-wait")] = False,
    plain: PlainOption = False,
) -> None:
    execute_command(
        "process",
        ProcessReconcileInput(
            output=output_options(plain=plain),
            project=project_options(project),
            workspace=workspace,
            run_id=run_id,
            no_wait=no_wait,
        ),
        process_handlers.reconcile_process,
    )
