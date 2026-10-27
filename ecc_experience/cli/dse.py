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
    spec: str | None = None
    omission_evidence: str | None = None
    resume: bool = False
    select: str | None = None
    max_concurrent: int | None = None
    other_plan: str | None = None
    other_result: str | None = None


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
            limits=None if command.spec else command.limits or {},
            release=command.release,
            spec=command.spec,
        )
        return CommandResult.ok([{"experience": "dse_plan", **result}])

    return _guard(operation)


def _run(command: DseInput, _context: CommandContext) -> CommandResult:
    def operation():
        from ecc_experience.api import dse_run

        result = dse_run(
            command.plan_path or "",
            command.output_path,
            model_release=command.model_release,
            max_concurrent=command.max_concurrent,
            resume=command.resume,
            select=command.select,
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
    parameters: Annotated[
        list[str] | None, typer.Option("--param", help="KEY=A,B (repeatable)")
    ] = None,
    through_step: Annotated[str | None, typer.Option("--through-step")] = None,
    metric: Annotated[str | None, typer.Option("--metric")] = None,
    unit: Annotated[str | None, typer.Option("--unit")] = None,
    max_trials: Annotated[int | None, typer.Option("--max-trials", min=3, max=100)] = None,
    max_seconds: Annotated[int | None, typer.Option("--max-seconds", min=1)] = None,
    trial_timeout: Annotated[int | None, typer.Option("--trial-timeout", min=1)] = None,
    spec: Annotated[
        str | None, typer.Option("--spec", help="Version 2 DSE JSON specification")
    ] = None,
    direction: Annotated[str, typer.Option("--direction")] = "minimize",
    patience: Annotated[int, typer.Option("--patience", min=1)] = 3,
    release: Annotated[str | None, typer.Option("--release")] = None,
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    if spec and (
        direction != "minimize"
        or patience != 3
        or any(
            value is not None
            for value in (
                parameters,
                through_step,
                metric,
                unit,
                max_trials,
                max_seconds,
                trial_timeout,
                release,
            )
        )
    ):
        raise typer.BadParameter("Use either --spec or legacy grid options")
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
        spec=spec,
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
    resume: Annotated[bool, typer.Option("--resume")] = False,
    select: Annotated[str | None, typer.Option("--select")] = None,
    max_concurrent: Annotated[int | None, typer.Option("--max-concurrent", min=1, max=16)] = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command = DseInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(None),
        output_path=output,
        plan_path=plan,
        model_release=model_release,
        resume=resume,
        select=select,
        max_concurrent=max_concurrent,
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


@dse_app.command("compare", help="Export a verified equal-budget receipt for two DSE runs")
def compare_cmd(
    *,
    plan: Annotated[str, typer.Option("--plan")],
    result: Annotated[str, typer.Option("--result")],
    other_plan: Annotated[str, typer.Option("--other-plan")],
    other_result: Annotated[str, typer.Option("--other-result")],
    output: Annotated[str, typer.Option("--output")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    def handle(command: DseInput, _context: CommandContext) -> CommandResult:
        def operation():
            from ecc_experience.api import dse_compare

            if (
                command.plan_path is None
                or command.result_path is None
                or command.other_plan is None
                or command.other_result is None
            ):
                raise typer.BadParameter("Comparison requires two plan/result pairs")
            report = dse_compare(
                command.plan_path,
                command.result_path,
                command.other_plan,
                command.other_result,
                command.output_path,
            )
            return CommandResult.ok([{"experience": "dse_compare", **report}])

        return _guard(operation)

    execute_command(
        "experience",
        DseInput(
            output=output_options(plain=plain, json_output=json_output),
            project=project_options(None),
            output_path=output,
            plan_path=plan,
            result_path=result,
            other_plan=other_plan,
            other_result=other_result,
        ),
        handle,
    )


@dse_app.command("d4", help="Evaluate equal-budget grid/adaptive/warm/model DSE evidence")
def d4_cmd(
    *,
    spec: Annotated[str, typer.Option("--spec", help="D4 run matrix JSON")],
    output: Annotated[str, typer.Option("--output")],
    omission_evidence: Annotated[
        str | None,
        typer.Option(
            "--omission-evidence",
            help="JSON evidence for explicitly omitted optional strategies",
        ),
    ] = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    def handle(command: DseInput, _context: CommandContext) -> CommandResult:
        def operation():
            from ecc_experience.api import d4_evaluate

            report = d4_evaluate(
                command.spec or "",
                command.output_path,
                omission_evidence=command.omission_evidence,
            )
            return CommandResult(
                records=({"experience": "dse_d4", **report},),
                exit_code=report["exit_code"],
            )

        return _guard(operation)

    execute_command(
        "experience",
        DseInput(
            output=output_options(plain=plain, json_output=json_output),
            project=project_options(None),
            output_path=output,
            spec=spec,
            omission_evidence=omission_evidence,
        ),
        handle,
    )
