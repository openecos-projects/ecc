import os
import sys
from collections.abc import Callable

from chipcompiler.cli.command_inputs import LogInput
from chipcompiler.cli.invocation import CommandInput
from chipcompiler.cli.param_handler import (
    render_param_diff_text,
    render_param_list_text,
    render_param_set_text,
    render_param_show_text,
)
from chipcompiler.cli.render import render_result
from chipcompiler.cli.types import CommandContext, CommandResult, OutputMode

Renderer = Callable[[CommandResult, CommandContext, CommandInput, bool], None]
RendererKey = tuple[str, OutputMode]
ParamTextRenderer = Callable[[tuple[dict, ...]], None]


def render_command_result(
    command: str,
    render_key: str,
    result: CommandResult,
    ctx: CommandContext,
    command_input: CommandInput,
    color: bool,
) -> None:
    renderer = RENDERERS.get((render_key, ctx.output_mode))
    if renderer is not None:
        renderer(result, ctx, command_input, color)
        return

    render_result(result, ctx.output_mode, command=command, color=color)


def _render_param_text(render_text: ParamTextRenderer) -> Renderer:
    def renderer(
        result: CommandResult,
        ctx: CommandContext,
        command_input: CommandInput,
        color: bool,
    ) -> None:
        from chipcompiler.cli.pretty import render_error

        if result.exit_code != 0:
            render_error(result.records, color=color)
            return
        render_text(result.records)

    return renderer


def _render_log_text(
    result: CommandResult,
    ctx: CommandContext,
    command_input: CommandInput,
    color: bool,
) -> None:
    from chipcompiler.cli.log_view import (
        render_log_listing_pretty,
        render_log_pretty,
        tail_lines_for_log,
    )
    from chipcompiler.cli.pretty import render_error, render_generic_block

    if not isinstance(command_input, LogInput):
        raise TypeError("log renderer requires LogInput")

    if command_input.errors:
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
    if ctx.run_dir:
        tail_map = {}
        for rec in records:
            source = rec.get("source") or rec.get("log", "")
            if not source:
                continue
            full_path = os.path.join(ctx.run_dir, source)
            lines = tail_lines_for_log(full_path)
            if lines:
                tail_map[source] = lines

    render_log_listing_pretty(list(records), color=color, tail_map=tail_map)


def _render_log_plain(
    result: CommandResult,
    ctx: CommandContext,
    command_input: CommandInput,
    color: bool,
) -> None:
    from chipcompiler.cli.log_view import render_log_records_plain

    records = result.records
    if not records:
        return

    if "line_no" in records[0]:
        render_log_records_plain(records)
        return

    render_result(result, OutputMode.PLAIN)


RENDERERS: dict[RendererKey, Renderer] = {
    ("param:list", OutputMode.TEXT): _render_param_text(render_param_list_text),
    ("param:show", OutputMode.TEXT): _render_param_text(render_param_show_text),
    ("param:set", OutputMode.TEXT): _render_param_text(render_param_set_text),
    ("param:unset", OutputMode.TEXT): _render_param_text(render_param_set_text),
    ("param:diff", OutputMode.TEXT): _render_param_text(render_param_diff_text),
    ("log", OutputMode.TEXT): _render_log_text,
    ("log", OutputMode.PLAIN): _render_log_plain,
}
