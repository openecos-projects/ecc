from dataclasses import dataclass
from typing import Annotated

import typer

from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.inputs import (
    OutputOptions,
    ProjectOptions,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import JsonOption, PlainOption, ProjectOption, WorkspaceOption
from chipcompiler.cli.core.records import manifest_error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from ecc_experience.cli.handlers import _guard

dse_app = create_app(help="Screen early PNR stages and validate full-flow winners")


@dataclass(frozen=True)
class DseInput:
    output: OutputOptions
    project: ProjectOptions
    output_path: str
    workspace: str | None = None
    store: str | None = None
    plan_path: str | None = None
    parameters: list[str] | None = None
    through_step: str | None = None
    metric: str | None = None
    unit: str | None = None
    direction: str = "minimize"
    limits: dict | None = None
    release: str | None = None
    model_release: str | None = None
    result_path: str | None = None


def _plan(command: DseInput, context: CommandContext) -> CommandResult:
    if context.manifest_error:
        return CommandResult.err([manifest_error_record(context.manifest_error)])

    def operation():
        from ecc_experience.api import dse_plan

        result = dse_plan(
            context.project_dir,
            context.run_dir,
            command.store or "",
            command.output_path,
            parameters=command.parameters or [],
            through_step=command.through_step or "",
            metric=command.metric or "",
            unit=command.unit or "",
            direction=command.direction,
            limits=command.limits or {},
            release=command.release,
        )
        return CommandResult.ok([{"experience": "dse_plan", **result}])

    return _guard(operation)


def _run(command: DseInput, _context: CommandContext) -> CommandResult:
    def operation():
        from ecc_experience.api import dse_run

        result = dse_run(
            command.plan_path or "", command.output_path, model_release=command.model_release
        )
        return CommandResult(
            records=({"experience": "dse_run", **result},), exit_code=result["exit_code"]
        )

    return _guard(operation)


@dse_app.command("plan", help="Freeze a reviewed parameter grid and stage objective")
def plan_cmd(
    *,
    store: Annotated[str, typer.Option("--store")],
    output: Annotated[str, typer.Option("--output")],
    parameters: Annotated[list[str], typer.Option("--param", help="KEY=A,B (repeatable)")],
    through_step: Annotated[str, typer.Option("--through-step")],
    metric: Annotated[str, typer.Option("--metric")],
    unit: Annotated[str, typer.Option("--unit")],
    max_trials: Annotated[int, typer.Option("--max-trials", min=3, max=100)],
    max_seconds: Annotated[int, typer.Option("--max-seconds", min=1)],
    trial_timeout: Annotated[int, typer.Option("--trial-timeout", min=1)],
    direction: Annotated[str, typer.Option("--direction")] = "minimize",
    patience: Annotated[int, typer.Option("--patience", min=1)] = 3,
    release: Annotated[str | None, typer.Option("--release")] = None,
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command = DseInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
        output_path=output,
        workspace=workspace,
        store=store,
        parameters=parameters,
        through_step=through_step,
        metric=metric,
        unit=unit,
        direction=direction,
        release=release,
        limits={
            "max_trials": max_trials,
            "max_seconds": max_seconds,
            "trial_timeout_seconds": trial_timeout,
            "patience": patience,
        },
    )
    execute_command("experience", command, _plan)


@dse_app.command("run", help="Execute a frozen DSE plan including full and fresh validation")
def run_cmd(
    *,
    plan: Annotated[str, typer.Option("--plan")],
    output: Annotated[str, typer.Option("--output")],
    model_release: Annotated[str | None, typer.Option("--model-release")] = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command = DseInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(None),
        output_path=output,
        plan_path=plan,
        model_release=model_release,
    )
    execute_command("experience", command, _run)


@dse_app.command("report", help="Summarize measured DSE outcomes and freeze verified feedback")
def report_cmd(
    *,
    plan: Annotated[str, typer.Option("--plan")],
    result: Annotated[str, typer.Option("--result")],
    output: Annotated[str, typer.Option("--output")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    def handle(command: DseInput, _context: CommandContext) -> CommandResult:
        def operation():
            from ecc_experience.api import dse_report

            report = dse_report(
                command.plan_path or "", command.result_path or "", command.output_path
            )
            return CommandResult.ok([{"experience": "dse_report", **report}])

        return _guard(operation)

    execute_command(
        "experience",
        DseInput(
            output=output_options(plain=plain, json_output=json_output),
            project=project_options(None),
            output_path=output,
            plan_path=plan,
            result_path=result,
        ),
        handle,
    )
