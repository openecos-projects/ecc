import os
import sys
from collections.abc import Callable
from typing import Protocol, TypeVar

import typer

from chipcompiler.cli.command_inputs import OutputOptions, ProjectOptions
from chipcompiler.cli.config import resolve_project_dir
from chipcompiler.cli.inspect import resolve_run_dir
from chipcompiler.cli.render import render_result
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

    if command == "param" and ctx.output_mode == OutputMode.TEXT:
        _render_param_text(selected_render_key, result, color=color)
    elif command == "log" and ctx.output_mode == OutputMode.TEXT:
        _render_log_text(command_input, result, color=color, run_dir=ctx.run_dir)
    elif command == "log" and ctx.output_mode == OutputMode.PLAIN:
        _render_log_plain(result)
    else:
        render_result(result, ctx.output_mode, command=command, color=color)

    raise typer.Exit(code=result.exit_code)


def _render_param_text(render_key: str, result, color=True) -> None:
    from chipcompiler.cli.param_handler import (
        render_param_diff_text,
        render_param_list_text,
        render_param_set_text,
        render_param_show_text,
    )
    from chipcompiler.cli.pretty import render_error

    if result.exit_code != 0:
        render_error(result.records, color=color)
        return

    renderers = {
        "list": render_param_list_text,
        "show": render_param_show_text,
        "set": render_param_set_text,
        "unset": render_param_set_text,
        "diff": render_param_diff_text,
    }
    _, _, subcmd = render_key.partition(":")
    renderer = renderers.get(subcmd)
    if renderer:
        renderer(result.records)
    else:
        render_result(result, OutputMode.PLAIN)


def _render_log_text(command_input: CommandInput, result, color=True, run_dir=None) -> None:
    from chipcompiler.cli.log_view import (
        render_log_listing_pretty,
        render_log_pretty,
        tail_lines_for_log,
    )
    from chipcompiler.cli.pretty import render_error, render_generic_block

    if getattr(command_input, "errors", False):
        print("warning: --errors is deprecated and no longer filters output", file=sys.stderr)

    if result.exit_code != 0:
        render_error(result.records, color=color)
        return

    records = result.records
    if not records:
        return

    first = records[0]

    if "log_status" in first or "status" in first:
        render_generic_block(records, color=color, tag="log")
        return

    if "line_no" in first:
        inspect_cmd = first.get("inspect_cmd", "")
        current_source = None
        current_lines = []
        current_step = first["step"]
        for rec in records:
            src = rec["source"]
            if src != current_source:
                if current_source is not None:
                    render_log_pretty(
                        current_step,
                        current_source,
                        current_lines,
                        inspect_cmd,
                        color=color,
                    )
                current_source = src
                current_lines = []
            current_lines.append(rec["line"])
        if current_source is not None:
            render_log_pretty(
                current_step,
                current_source,
                current_lines,
                inspect_cmd,
                color=color,
            )
        return

    tail_map = None
    if run_dir:
        tail_map = {}
        for rec in records:
            source = rec.get("source") or rec.get("log", "")
            if not source:
                continue
            full_path = os.path.join(run_dir, source)
            lines = tail_lines_for_log(full_path)
            if lines:
                tail_map[source] = lines

    render_log_listing_pretty(list(records), color=color, tail_map=tail_map)


def _render_log_plain(result) -> None:
    from chipcompiler.cli.log_view import render_log_records_plain

    records = result.records
    if not records:
        return

    if "line_no" in records[0]:
        render_log_records_plain(records)
        return

    render_result(result, OutputMode.PLAIN)
