import sys
from collections.abc import Callable
from typing import Protocol, TypeVar

import typer

from chipcompiler.cli.command_inputs import OutputOptions, ProjectOptions
from chipcompiler.cli.config import resolve_project_dir
from chipcompiler.cli.inspect import resolve_run_dir
from chipcompiler.cli.types import CommandContext, CommandResult, OutputMode


class CommandInput(Protocol):
    output: OutputOptions
    project: ProjectOptions


CommandInputT = TypeVar("CommandInputT", bound=CommandInput)
CommandHandler = Callable[[CommandInputT, CommandContext], CommandResult]


def output_mode(json_output: bool, jsonl: bool, plain: bool) -> OutputMode:
    if jsonl:
        return OutputMode.JSONL
    if json_output:
        return OutputMode.JSON
    if plain:
        return OutputMode.PLAIN
    return OutputMode.TEXT


def build_context(command_input: CommandInput) -> CommandContext:
    project = command_input.project.project
    project_dir = resolve_project_dir(project)

    run_id = command_input.project.run_id
    run_dir, run_id = resolve_run_dir(project_dir, run_id)

    mode = output_mode(
        command_input.output.json,
        command_input.output.jsonl,
        command_input.output.plain,
    )

    return CommandContext(
        project_dir=project_dir,
        project=project,
        run_dir=run_dir,
        run_id=run_id,
        output_mode=mode,
    )


def _should_colorize():
    from chipcompiler.cli.pretty import supports_color

    return supports_color(file=sys.stdout)


def execute_command(
    command: str,
    command_input: CommandInputT,
    handler: CommandHandler[CommandInputT],
    render_key: str | None = None,
) -> None:
    ctx = build_context(command_input)
    result = handler(command_input, ctx)
    color = _should_colorize()
    selected_render_key = render_key or command

    from chipcompiler.cli.renderers import render_command_result

    render_command_result(command, selected_render_key, result, ctx, command_input, color)

    raise typer.Exit(code=result.exit_code)
