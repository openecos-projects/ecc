import argparse
import sys
from collections.abc import Sequence

from chipcompiler.cli.commands import build_context, dispatch
from chipcompiler.cli.render import render_result
from chipcompiler.cli.types import OutputMode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecc",
        description="ECC - EDA toolchain for RTL-to-GDS flows",
    )
    subparsers = parser.add_subparsers(dest="command")

    # ecc init
    init_parser = subparsers.add_parser("init", help="Create a new project skeleton")
    init_parser.add_argument("name", help="Project name")

    # ecc check
    check_parser = subparsers.add_parser("check", help="Validate project configuration")
    _add_project_arg(check_parser)
    check_parser.add_argument("--json", action="store_true", help="JSON output")

    # ecc run
    run_parser = subparsers.add_parser("run", help="Execute the complete flow")
    _add_project_arg(run_parser)
    run_parser.add_argument("--overwrite", action="store_true",
                            help="Remove existing runs/default before running")
    run_parser.add_argument("--json", action="store_true", help="JSON output")
    run_parser.add_argument("--jsonl", action="store_true", help="JSONL output")

    # ecc status
    status_parser = subparsers.add_parser("status", help="Show run and step status")
    _add_project_arg(status_parser)
    status_parser.add_argument("--json", action="store_true", help="JSON output")
    status_parser.add_argument("--jsonl", action="store_true", help="JSONL output")
    status_parser.add_argument("--run-id", default=None, dest="run_id",
                               help="Run workspace selector")

    # ecc log
    log_parser = subparsers.add_parser("log", help="Inspect step logs")
    _add_project_arg(log_parser)
    log_parser.add_argument("step", nargs="?", default=None, help="Step name")
    log_parser.add_argument("--errors", action="store_true",
                            help=argparse.SUPPRESS)
    log_parser.add_argument("--plain", action="store_true", help="Plain key-value output")
    log_parser.add_argument("--jsonl", action="store_true", help="JSONL output")
    log_parser.add_argument("--run-id", default=None, dest="run_id",
                            help="Run workspace selector")

    # ecc metrics
    metrics_parser = subparsers.add_parser("metrics", help="Show step metrics")
    _add_project_arg(metrics_parser)
    metrics_parser.add_argument("step", nargs="?", default=None, help="Step name")
    metrics_parser.add_argument("--json", action="store_true", help="JSON output")
    metrics_parser.add_argument("--jsonl", action="store_true", help="JSONL output")
    metrics_parser.add_argument("--run-id", default=None, dest="run_id",
                                help="Run workspace selector")

    # ecc artifacts
    artifacts_parser = subparsers.add_parser("artifacts", help="List generated files")
    _add_project_arg(artifacts_parser)
    artifacts_parser.add_argument("step", nargs="?", default=None, help="Step name")
    artifacts_parser.add_argument("--json", action="store_true", help="JSON output")
    artifacts_parser.add_argument("--jsonl", action="store_true", help="JSONL output")
    artifacts_parser.add_argument("--run-id", default=None, dest="run_id",
                                  help="Run workspace selector")

    # ecc config
    config_parser = subparsers.add_parser("config", help="Show configuration")
    _add_project_arg(config_parser)
    config_parser.add_argument("step", nargs="?", default=None, help="Step name")
    config_parser.add_argument("--resolved", action="store_true", required=True,
                               help="Show resolved configuration")
    config_parser.add_argument("--json", action="store_true", help="JSON output")
    config_parser.add_argument("--jsonl", action="store_true", help="JSONL output")
    config_parser.add_argument("--run-id", default=None, dest="run_id",
                               help="Run workspace selector")

    # ecc diagnose
    diagnose_parser = subparsers.add_parser("diagnose", help="Show run diagnostics")
    _add_project_arg(diagnose_parser)
    diagnose_parser.add_argument("step", nargs="?", default=None, help="Step name")
    diagnose_parser.add_argument("--json", action="store_true", help="JSON output")
    diagnose_parser.add_argument("--jsonl", action="store_true", help="JSONL output")
    diagnose_parser.add_argument("--run-id", default=None, dest="run_id",
                                 help="Run workspace selector")

    # ecc param
    param_parser = subparsers.add_parser("param", help="Manage EDA parameters")
    param_sub = param_parser.add_subparsers(dest="param_command")

    def _add_param_flags(p):
        _add_project_arg(p)
        p.add_argument("--json", action="store_true", help="JSON output")
        p.add_argument("--jsonl", action="store_true", help="JSONL output")
        p.add_argument("--plain", action="store_true", help="Plain key-value output")

    # ecc param list
    param_list = param_sub.add_parser("list", help="List all parameters")
    _add_param_flags(param_list)

    # ecc param show
    param_show = param_sub.add_parser("show", help="Show parameter details")
    _add_param_flags(param_show)
    param_show.add_argument("key", help="Parameter key (e.g. place.target_density)")

    # ecc param set
    param_set = param_sub.add_parser("set", help="Set a persistent parameter override")
    _add_param_flags(param_set)
    param_set.add_argument("key", help="Parameter key")
    param_set.add_argument("value", help="Parameter value")

    # ecc param unset
    param_unset = param_sub.add_parser("unset", help="Remove a persistent override")
    _add_param_flags(param_unset)
    param_unset.add_argument("key", help="Parameter key")

    # ecc param diff
    param_diff = param_sub.add_parser("diff", help="Show overrides that differ from defaults")
    _add_param_flags(param_diff)

    # ecc run --set
    run_parser.add_argument("--set", action="append", default=[], dest="param_set",
                            help="Set parameter override (repeatable, e.g. --set place.target_density=0.65)")
    run_parser.add_argument("--plain", action="store_true", help="Plain key-value output")

    return parser


def _add_project_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", default=None,
                        help="Project directory (default: current directory)")


def _render_param_text(args, result) -> None:
    from chipcompiler.cli.param_handler import (
        render_param_diff_text,
        render_param_list_text,
        render_param_set_text,
        render_param_show_text,
    )
    if result.exit_code != 0:
        render_result(result, OutputMode.PLAIN)
        return

    subcmd = getattr(args, "param_command", None)
    if subcmd == "list":
        render_param_list_text(result.records)
    elif subcmd == "show":
        render_param_show_text(result.records)
    elif subcmd in ("set", "unset"):
        render_param_set_text(result.records)
    elif subcmd == "diff":
        render_param_diff_text(result.records)
    else:
        render_result(result, OutputMode.PLAIN)


def _should_colorize():
    import os
    if not sys.stdout.isatty():
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    return True


def _render_log_text(args, result) -> None:
    from chipcompiler.cli.log_view import (
        render_log_listing_pretty,
        render_log_pretty,
    )

    if getattr(args, "errors", False):
        print("warning: --errors is deprecated and no longer filters output", file=sys.stderr)

    if result.exit_code != 0:
        render_result(result, OutputMode.PLAIN)
        return

    records = result.records
    if not records:
        return

    first = records[0]

    # Status/sentinel records (no_logs, empty, etc.)
    if "log_status" in first or "status" in first:
        render_result(result, OutputMode.PLAIN)
        return

    color = _should_colorize()

    # Step mode: records have line_no and kind
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
                        current_step, current_source, current_lines,
                        inspect_cmd, color=color,
                    )
                current_source = src
                current_lines = []
            current_lines.append(rec["line"])
        if current_source is not None:
            render_log_pretty(
                current_step, current_source, current_lines,
                inspect_cmd, color=color,
            )
        return

    # Listing mode
    render_log_listing_pretty(list(records), color=color)


def _render_log_plain(result) -> None:
    from chipcompiler.cli.log_view import render_log_records_plain

    records = result.records
    if not records:
        return
    first = records[0]

    if "log_status" in first or "status" in first:
        render_result(result, OutputMode.PLAIN)
        return

    if "line_no" in first:
        render_log_records_plain(records)
        return

    render_result(result, OutputMode.PLAIN)


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command is None:
        parser.print_help()
        return 1

    ctx = build_context(args)
    result = dispatch(args, ctx)

    if args.command == "param" and ctx.output_mode == OutputMode.TEXT:
        _render_param_text(args, result)
    elif args.command == "log" and ctx.output_mode == OutputMode.TEXT:
        _render_log_text(args, result)
    elif args.command == "log" and ctx.output_mode == OutputMode.PLAIN:
        _render_log_plain(result)
    else:
        render_result(result, ctx.output_mode)

    return result.exit_code


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
