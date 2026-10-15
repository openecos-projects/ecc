from dataclasses import dataclass
from typing import Annotated

import typer

from chipcompiler.cli.core.inputs import (
    OutputOptions,
    ProjectOptions,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import JsonOption, PlainOption
from chipcompiler.cli.core.types import CommandContext, CommandResult
from ecc_experience.cli.handlers import _guard


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
