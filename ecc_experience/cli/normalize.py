"""CLI registration for provenance-preserving multi-store normalization."""

from dataclasses import dataclass
from typing import Annotated

import typer

from chipcompiler.cli.core.inputs import OutputOptions, ProjectOptions, output_options
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import JsonOption, PlainOption
from chipcompiler.cli.core.types import CommandContext, CommandResult
from ecc_experience.cli.handlers import _guard


@dataclass(frozen=True)
class NormalizeInput:
    output: OutputOptions
    stores: list[str]
    output_path: str
    project: ProjectOptions = ProjectOptions()


def _execute(command: NormalizeInput, _context: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import normalize

        result = normalize(command.stores, command.output_path)
        return CommandResult(
            records=({"experience": "normalize", **result},), exit_code=result["exit_code"]
        )

    return _guard(operation)


def register_normalize(app: typer.Typer) -> None:
    @app.command("normalize", help="Build a read-only manifest across experience stores")
    def normalize_cmd(
        *,
        store: Annotated[
            list[str], typer.Option("--store", help="Source store; repeat to combine")
        ],
        output: Annotated[
            str, typer.Option("--output", help="New directory outside source stores")
        ],
        plain: PlainOption = False,
        json_output: JsonOption = False,
    ) -> None:
        execute_command(
            "experience",
            NormalizeInput(
                output=output_options(plain=plain, json_output=json_output),
                stores=store,
                output_path=output,
            ),
            _execute,
        )
