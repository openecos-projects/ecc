import os
import sys
from types import SimpleNamespace

import typer

from chipcompiler.cli.commands import build_context, dispatch
from chipcompiler.cli.render import render_result
from chipcompiler.cli.types import OutputMode


def output_mode(json_output: bool, jsonl: bool, plain: bool) -> OutputMode:
    if jsonl:
        return OutputMode.JSONL
    if json_output:
        return OutputMode.JSON
    if plain:
        return OutputMode.PLAIN
    return OutputMode.TEXT


def command_args(command: str, **kwargs) -> SimpleNamespace:
    return SimpleNamespace(command=command, **kwargs)


def _should_colorize():
    from chipcompiler.cli.pretty import supports_color
    return supports_color(file=sys.stdout)


def finish_command(args) -> None:
    ctx = build_context(args)
    result = dispatch(args, ctx)
    color = _should_colorize()

    if args.command == "param" and ctx.output_mode == OutputMode.TEXT:
        _render_param_text(args, result, color=color)
    elif args.command == "log" and ctx.output_mode == OutputMode.TEXT:
        _render_log_text(args, result, color=color, run_dir=ctx.run_dir)
    elif args.command == "log" and ctx.output_mode == OutputMode.PLAIN:
        _render_log_plain(result)
    else:
        render_result(result, ctx.output_mode, command=args.command, color=color)

    raise typer.Exit(code=result.exit_code)


def _render_param_text(args, result, color=True) -> None:
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
    subcmd = getattr(args, "param_command", None)
    renderer = renderers.get(subcmd)
    if renderer:
        renderer(result.records)
    else:
        render_result(result, OutputMode.PLAIN)


def _render_log_text(args, result, color=True, run_dir=None) -> None:
    from chipcompiler.cli.log_view import (
        render_log_listing_pretty,
        render_log_pretty,
        tail_lines_for_log,
    )
    from chipcompiler.cli.pretty import render_error, render_generic_block

    if getattr(args, "errors", False):
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
