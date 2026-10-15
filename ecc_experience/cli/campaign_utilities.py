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
from chipcompiler.cli.core.options import JsonOption, PlainOption
from chipcompiler.cli.core.types import CommandContext, CommandResult
from ecc_experience.cli import handlers
from ecc_experience.cli.handlers import _guard
from ecc_experience.cli.inputs import BenchmarkPlanInput, BenchmarkSpecInput, CampaignAnalysisInput


@dataclass(frozen=True)
class CampaignUtilityInput:
    output: OutputOptions
    source: str
    output_path: str
    ledger: str | None = None
    project: ProjectOptions = project_options(None)


def register_commands(app: typer.Typer) -> None:
    @app.command(
        "create", help="Prepare explicit project sources in an organized campaign directory"
    )
    def create_cmd(
        *,
        spec: Annotated[str, typer.Option("--spec")],
        output: Annotated[str, typer.Option("--output")],
        plain: PlainOption = False,
        json_output: JsonOption = False,
    ) -> None:
        execute_command(
            "experience",
            CampaignUtilityInput(
                output_options(plain=plain, json_output=json_output), spec, output
            ),
            _create,
        )

    @app.command("report", help="Export every campaign attempt as JSON, CSV and Markdown matrices")
    def report_cmd(
        *,
        manifest: Annotated[str, typer.Option("--manifest")],
        output: Annotated[str, typer.Option("--output")],
        ledger: Annotated[str | None, typer.Option("--ledger")] = None,
        plain: PlainOption = False,
        json_output: JsonOption = False,
    ) -> None:
        execute_command(
            "experience",
            CampaignUtilityInput(
                output_options(plain=plain, json_output=json_output), manifest, output, ledger
            ),
            _report,
        )

    @app.command("matrix", help="Aggregate real design observations into a matrix")
    def matrix_cmd(
        *,
        inputs: Annotated[str, typer.Option("--inputs")],
        expected_designs: Annotated[str, typer.Option("--expected-designs")],
        output: Annotated[str, typer.Option("--output")],
        families: Annotated[str | None, typer.Option("--families")] = None,
        plain: PlainOption = False,
        json_output: JsonOption = False,
    ) -> None:
        execute_command(
            "experience",
            CampaignAnalysisInput(
                output_options(plain=plain, json_output=json_output),
                inputs,
                output,
                secondary=expected_designs,
                auxiliary=families,
            ),
            handlers.campaign_matrix,
        )

    @app.command("readiness", help="Check whether a matrix is ready for evaluation")
    def readiness_cmd(
        *,
        matrix: Annotated[str, typer.Option("--matrix")],
        output: Annotated[str, typer.Option("--output")],
        min_independent_designs: Annotated[int, typer.Option("--min-independent-designs")] = 3,
        min_families: Annotated[int, typer.Option("--min-families")] = 2,
        min_candidate_configurations: Annotated[
            int, typer.Option("--min-candidate-configurations")
        ] = 2,
        plain: PlainOption = False,
        json_output: JsonOption = False,
    ) -> None:
        execute_command(
            "experience",
            CampaignAnalysisInput(
                output_options(plain=plain, json_output=json_output),
                matrix,
                output,
                min_independent_designs=min_independent_designs,
                min_families=min_families,
                min_candidate_configurations=min_candidate_configurations,
            ),
            handlers.campaign_readiness,
        )

    @app.command("archive", help="Create a path-redacted campaign evidence archive")
    def archive_cmd(
        *,
        manifest: Annotated[str, typer.Option("--manifest")],
        report: Annotated[str, typer.Option("--report")],
        output: Annotated[str, typer.Option("--output")],
        plain: PlainOption = False,
        json_output: JsonOption = False,
    ) -> None:
        execute_command(
            "experience",
            CampaignAnalysisInput(
                output_options(plain=plain, json_output=json_output),
                manifest,
                output,
                secondary=report,
            ),
            handlers.campaign_archive,
        )

    @app.command("effect", help="Compare candidate trials with their baselines")
    def effect_cmd(
        *,
        report: Annotated[str, typer.Option("--report")],
        output: Annotated[str, typer.Option("--output")],
        baselines: Annotated[str | None, typer.Option("--baselines")] = None,
        plain: PlainOption = False,
        json_output: JsonOption = False,
    ) -> None:
        execute_command(
            "experience",
            CampaignAnalysisInput(
                output_options(plain=plain, json_output=json_output),
                report,
                output,
                auxiliary=baselines,
            ),
            handlers.campaign_effect,
        )

    benchmark_app = create_app(help="Validate execution-neutral benchmark specifications")

    @benchmark_app.command("validate", help="Validate a benchmark spec without running EDA")
    def benchmark_validate_cmd(
        *,
        spec: Annotated[str, typer.Option("--spec")],
        plain: PlainOption = False,
        json_output: JsonOption = False,
    ) -> None:
        execute_command(
            "experience",
            BenchmarkSpecInput(output_options(plain=plain, json_output=json_output), spec),
            handlers.validate_benchmark_spec,
        )

    @benchmark_app.command("plan", help="Materialize a benchmark plan without running EDA")
    def benchmark_plan_cmd(
        *,
        spec: Annotated[str, typer.Option("--spec")],
        output: Annotated[str, typer.Option("--output")],
        plain: PlainOption = False,
        json_output: JsonOption = False,
    ) -> None:
        execute_command(
            "experience",
            BenchmarkPlanInput(output_options(plain=plain, json_output=json_output), spec, output),
            handlers.prepare_benchmark,
        )

    app.add_typer(benchmark_app, name="benchmark")


def _create(command: CampaignUtilityInput, _context: CommandContext) -> CommandResult:
    def operation():
        from ecc_experience.api import campaign_create

        result = campaign_create(command.source, command.output_path)
        return CommandResult.ok([{"experience": "campaign_create", **result}])

    return _guard(operation)


def _report(command: CampaignUtilityInput, _context: CommandContext) -> CommandResult:
    def operation():
        from ecc_experience.api import campaign_report

        result = campaign_report(command.source, command.output_path, ledger=command.ledger)
        return CommandResult(
            records=({"experience": "campaign_report", **result},), exit_code=result["exit_code"]
        )

    return _guard(operation)
