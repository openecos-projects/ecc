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

knowledge_app = create_app(help="Review benchmark-driven candidate knowledge and cohort bridges")


@dataclass(frozen=True)
class KnowledgeInput:
    output: OutputOptions
    output_path: str
    source: str | None = None
    previous_release: str | None = None
    heldout: str | None = None
    active_cohort: str | None = None
    direction: str = "minimize"
    project: ProjectOptions = project_options(None)


@knowledge_app.command("manifest", help="Freeze a D4 report into a candidate campaign manifest")
def manifest_cmd(
    *,
    report: Annotated[str, typer.Option("--report", help="Completed D4 report JSON")],
    output: Annotated[str, typer.Option("--output")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    def handle(command: KnowledgeInput, _context: CommandContext) -> CommandResult:
        def operation() -> CommandResult:
            from ecc_experience.api import campaign_manifest

            result = campaign_manifest(command.source or "", command.output_path)
            return CommandResult.ok([{"experience": "knowledge_manifest", **result}])

        return _guard(operation)

    execute_command(
        "experience",
        KnowledgeInput(
            output=output_options(plain=plain, json_output=json_output),
            source=report,
            output_path=output,
        ),
        handle,
    )


@knowledge_app.command("delta", help="Compute candidate knowledge and cohort triage")
def delta_cmd(
    *,
    manifest: Annotated[str, typer.Option("--manifest")],
    output: Annotated[str, typer.Option("--output")],
    previous_release: Annotated[
        str | None, typer.Option("--previous-release", help="Previous model release JSON")
    ] = None,
    heldout: Annotated[
        str | None, typer.Option("--heldout", help="Independent held-out declaration JSON")
    ] = None,
    active_cohort: Annotated[str | None, typer.Option("--active-cohort")] = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    def handle(command: KnowledgeInput, _context: CommandContext) -> CommandResult:
        def operation() -> CommandResult:
            from ecc_experience.api import knowledge_delta

            result = knowledge_delta(
                command.source or "",
                command.output_path,
                previous_release=command.previous_release,
                heldout=command.heldout,
                active_cohort=command.active_cohort,
            )
            return CommandResult.ok([{"experience": "knowledge_delta", **result}])

        return _guard(operation)

    execute_command(
        "experience",
        KnowledgeInput(
            output=output_options(plain=plain, json_output=json_output),
            source=manifest,
            output_path=output,
            previous_release=previous_release,
            heldout=heldout,
            active_cohort=active_cohort,
        ),
        handle,
    )


@knowledge_app.command("bridge", help="Evaluate measured comparability between runtime cohorts")
def bridge_cmd(
    *,
    spec: Annotated[str, typer.Option("--spec", help="Bridge specification JSON")],
    output: Annotated[str, typer.Option("--output")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    def handle(command: KnowledgeInput, _context: CommandContext) -> CommandResult:
        def operation() -> CommandResult:
            from ecc_experience.api import knowledge_bridge

            result = knowledge_bridge(command.source or "", command.output_path)
            return CommandResult.ok([{"experience": "knowledge_bridge", **result}])

        return _guard(operation)

    execute_command(
        "experience",
        KnowledgeInput(
            output=output_options(plain=plain, json_output=json_output),
            source=spec,
            output_path=output,
        ),
        handle,
    )


@knowledge_app.command("drift", help="Recommend downgrade or retirement after measured drift")
def drift_cmd(
    *,
    observation: Annotated[str, typer.Option("--observation", help="Drift observation JSON")],
    output: Annotated[str, typer.Option("--output")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    def handle(command: KnowledgeInput, _context: CommandContext) -> CommandResult:
        def operation() -> CommandResult:
            from ecc_experience.api import knowledge_drift

            result = knowledge_drift(command.source or "", command.output_path)
            return CommandResult.ok([{"experience": "knowledge_drift", **result}])

        return _guard(operation)

    execute_command(
        "experience",
        KnowledgeInput(
            output=output_options(plain=plain, json_output=json_output),
            source=observation,
            output_path=output,
        ),
        handle,
    )


@knowledge_app.command("advice", help="Recommend a search strategy from paired campaign evidence")
def advice_cmd(
    *,
    manifest: Annotated[str, typer.Option("--manifest")],
    output: Annotated[str, typer.Option("--output")],
    direction: Annotated[str, typer.Option("--direction")] = "minimize",
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    def handle(command: KnowledgeInput, _context: CommandContext) -> CommandResult:
        def operation() -> CommandResult:
            from ecc_experience.api import strategy_advice

            result = strategy_advice(
                command.source or "", command.output_path, direction=command.direction
            )
            return CommandResult.ok([{"experience": "strategy_advice", **result}])

        return _guard(operation)

    execute_command(
        "experience",
        KnowledgeInput(
            output=output_options(plain=plain, json_output=json_output),
            source=manifest,
            output_path=output,
            direction=direction,
        ),
        handle,
    )


@knowledge_app.command(
    "next", help="Plan exploration and confirmation for the next benchmark round"
)
def next_cmd(
    *,
    manifest: Annotated[str, typer.Option("--manifest")],
    output: Annotated[str, typer.Option("--output")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    def handle(command: KnowledgeInput, _context: CommandContext) -> CommandResult:
        def operation() -> CommandResult:
            from ecc_experience.api import benchmark_next

            result = benchmark_next(command.source or "", command.output_path)
            return CommandResult.ok([{"experience": "benchmark_next", **result}])

        return _guard(operation)

    execute_command(
        "experience",
        KnowledgeInput(
            output=output_options(plain=plain, json_output=json_output),
            source=manifest,
            output_path=output,
        ),
        handle,
    )


@knowledge_app.command("champion", help="Compare champion and challenger release evidence")
def champion_cmd(
    *,
    spec: Annotated[str, typer.Option("--spec", help="Champion comparison JSON")],
    output: Annotated[str, typer.Option("--output")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    def handle(command: KnowledgeInput, _context: CommandContext) -> CommandResult:
        def operation() -> CommandResult:
            from ecc_experience.api import champion_compare

            result = champion_compare(command.source or "", command.output_path)
            return CommandResult.ok([{"experience": "champion_compare", **result}])

        return _guard(operation)

    execute_command(
        "experience",
        KnowledgeInput(
            output=output_options(plain=plain, json_output=json_output),
            source=spec,
            output_path=output,
        ),
        handle,
    )
