import sys
from collections.abc import Callable
from typing import Protocol, TypeVar

import typer

from chipcompiler.cli.core.inputs import OutputOptions, ProjectOptions
from chipcompiler.cli.core.types import CommandContext, CommandResult, OutputMode
from chipcompiler.cli.inspection.discovery import resolve_run_dir
from chipcompiler.cli.project.config import (
    InvalidFlowRun,
    config_run_id_from,
    load_run_config,
    resolve_project_dir,
)


class CommandInput(Protocol):
    output: OutputOptions
    project: ProjectOptions


CommandInputT = TypeVar("CommandInputT", bound=CommandInput)
CommandHandler = Callable[[CommandInputT, CommandContext], CommandResult]


def output_mode(*, json_output: bool, jsonl: bool, plain: bool) -> OutputMode:
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

    cli_run_id = command_input.project.run_id
    cfg = load_run_config(project_dir)
    configured = config_run_id_from(cfg)
    config_error = None
    if isinstance(configured, InvalidFlowRun):
        if cli_run_id is None:
            config_error = configured.problem
        configured = None

    run_dir, run_id = resolve_run_dir(
        project_dir, cli_run_id if cli_run_id is not None else configured
    )

    mode = output_mode(
        json_output=command_input.output.json,
        jsonl=command_input.output.jsonl,
        plain=command_input.output.plain,
    )

    return CommandContext(
        project_dir=project_dir,
        project=project,
        run_dir=run_dir,
        run_id=run_id,
        output_mode=mode,
        config_error=config_error,
        config=cfg,
    )


def _should_colorize():
    from chipcompiler.cli.rendering.pretty import supports_color

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

    from chipcompiler.cli.rendering.renderers import render_command_result

    render_command_result(command, selected_render_key, result, ctx, command_input, color=color)

    raise typer.Exit(code=result.exit_code)
