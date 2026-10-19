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
from ecc_experience.cli.handlers import _guard

study_app = create_app(help="Evaluate isolated held-out trials and publish verified feedback")


@dataclass(frozen=True)
class StudyInput:
    output: OutputOptions
    project: ProjectOptions
    source: str
    store: str
    destination: str
    publish: bool = False


def _execute(command: StudyInput, _context: CommandContext) -> CommandResult:
    def operation():
        from ecc_experience.api import study_evaluate, study_publish

        action = study_publish if command.publish else study_evaluate
        result = action(command.source, command.store, command.destination)
        return CommandResult(
            records=(
                {"experience": "study_publish" if command.publish else "study_evaluate", **result},
            ),
            exit_code=result.get("exit_code", 0),
        )

    return _guard(operation)


@study_app.command("evaluate", help="Evaluate explicit pairs against a frozen knowledge release")
def evaluate_cmd(
    *,
    spec: Annotated[str, typer.Option("--spec")],
    store: Annotated[str, typer.Option("--store")],
    output: Annotated[str, typer.Option("--output")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    execute_command(
        "experience",
        StudyInput(
            output_options(plain=plain, json_output=json_output),
            project_options(None),
            spec,
            store,
            output,
        ),
        _execute,
    )


@study_app.command(
    "publish", help="Recheck evaluation and release only explicitly isolated feedback"
)
def publish_cmd(
    *,
    evaluation: Annotated[str, typer.Option("--evaluation")],
    store: Annotated[str, typer.Option("--store")],
    output: Annotated[str, typer.Option("--output")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    execute_command(
        "experience",
        StudyInput(
            output_options(plain=plain, json_output=json_output),
            project_options(None),
            evaluation,
            store,
            output,
            publish=True,
        ),
        _execute,
    )
