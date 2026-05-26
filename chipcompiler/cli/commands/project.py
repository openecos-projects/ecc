from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import inspect as inspect_handlers
from chipcompiler.cli.command_handlers import project as project_handlers
from chipcompiler.cli.core.inputs import (
    CheckInput,
    ConfigInput,
    DiagnoseInput,
    InitInput,
    LogInput,
    RunInput,
    StatusInput,
    StepInspectInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import (
    JsonlOption,
    JsonOption,
    PlainOption,
    ProjectOption,
    RunIdOption,
)


def register_project_commands(app: typer.Typer) -> None:
    app.command("init", help="Create a new ECC project")(init_cmd)
    app.command("check", help="Validate the current project setup")(check_cmd)
    app.command("run", help="Run the configured RTL-to-GDS flow")(run_cmd)
    app.command("status", help="Show run and step status")(status_cmd)
    app.command("log", help="Show available logs or step log content")(log_cmd)
    app.command("metrics", help="Show run or step metrics")(metrics_cmd)
    app.command("artifacts", help="List generated artifacts")(artifacts_cmd)
    app.command("config", help="Show resolved project or step configuration")(config_cmd)
    app.command("diagnose", help="Diagnose run or step issues")(diagnose_cmd)


def init_cmd(
    name: Annotated[str, typer.Argument()],
    plain: PlainOption = False,
) -> None:
    command_input = InitInput(name=name, output=output_options(False, False, plain))
    execute_command("init", command_input, project_handlers.init)


def check_cmd(
    project: ProjectOption = None,
    json_output: JsonOption = False,
    plain: PlainOption = False,
) -> None:
    command_input = CheckInput(
        output=output_options(json_output, False, plain),
        project=project_options(project),
    )
    execute_command("check", command_input, project_handlers.check)


def run_cmd(
    project: ProjectOption = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
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
        output=output_options(json_output, jsonl, plain),
        project=project_options(project),
        overwrite=overwrite,
        param_set=tuple(param_set or ()),
    )
    execute_command("run", command_input, project_handlers.run)


def status_cmd(
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
    run_id: RunIdOption = None,
) -> None:
    command_input = StatusInput(
        output=output_options(json_output, jsonl, plain),
        project=project_options(project, run_id),
    )
    execute_command("status", command_input, inspect_handlers.status)


def log_cmd(
    step: Annotated[str | None, typer.Argument()] = None,
    project: ProjectOption = None,
    errors: Annotated[bool, typer.Option("--errors", hidden=True)] = False,
    json_output: JsonOption = False,
    plain: PlainOption = False,
    jsonl: JsonlOption = False,
    run_id: RunIdOption = None,
) -> None:
    command_input = LogInput(
        output=output_options(json_output, jsonl, plain),
        project=project_options(project, run_id),
        step=step,
        errors=errors,
    )
    execute_command("log", command_input, inspect_handlers.log)


def metrics_cmd(
    step: Annotated[str | None, typer.Argument()] = None,
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
    run_id: RunIdOption = None,
) -> None:
    command_input = StepInspectInput(
        output=output_options(json_output, jsonl, plain),
        project=project_options(project, run_id),
        step=step,
    )
    execute_command("metrics", command_input, inspect_handlers.metrics)


def artifacts_cmd(
    step: Annotated[str | None, typer.Argument()] = None,
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
    run_id: RunIdOption = None,
) -> None:
    command_input = StepInspectInput(
        output=output_options(json_output, jsonl, plain),
        project=project_options(project, run_id),
        step=step,
    )
    execute_command("artifacts", command_input, inspect_handlers.artifacts)


def config_cmd(
    step: Annotated[str | None, typer.Argument()] = None,
    resolved: Annotated[bool, typer.Option("--resolved")] = False,
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
    run_id: RunIdOption = None,
) -> None:
    if not resolved:
        raise typer.BadParameter("--resolved is required", param_hint="--resolved")
    command_input = ConfigInput(
        output=output_options(json_output, jsonl, plain),
        project=project_options(project, run_id),
        step=step,
        resolved=resolved,
    )
    execute_command("config", command_input, inspect_handlers.config)


def diagnose_cmd(
    step: Annotated[str | None, typer.Argument()] = None,
    project: ProjectOption = None,
    json_output: JsonOption = False,
    jsonl: JsonlOption = False,
    plain: PlainOption = False,
    run_id: RunIdOption = None,
) -> None:
    command_input = DiagnoseInput(
        output=output_options(json_output, jsonl, plain),
        project=project_options(project, run_id),
        step=step,
    )
    execute_command("diagnose", command_input, inspect_handlers.diagnose)
