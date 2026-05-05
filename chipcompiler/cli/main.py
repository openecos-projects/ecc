import argparse
import os
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
    init_parser.add_argument("--plain", action="store_true", help="Plain key-value output")

    # ecc check
    check_parser = subparsers.add_parser("check", help="Validate project configuration")
    _add_project_arg(check_parser)
    check_parser.add_argument("--json", action="store_true", help="JSON output")
    check_parser.add_argument("--plain", action="store_true", help="Plain key-value output")

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
    status_parser.add_argument("--plain", action="store_true", help="Plain key-value output")
    status_parser.add_argument("--run-id", default=None, dest="run_id",
                               help="Run workspace selector")

    # ecc log
    log_parser = subparsers.add_parser("log", help="Inspect step logs")
    _add_project_arg(log_parser)
    log_parser.add_argument("step", nargs="?", default=None, help="Step name")
    log_parser.add_argument("--errors", action="store_true",
                            help=argparse.SUPPRESS)
    log_parser.add_argument("--json", action="store_true", help="JSON output")
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
    metrics_parser.add_argument("--plain", action="store_true", help="Plain key-value output")
    metrics_parser.add_argument("--run-id", default=None, dest="run_id",
                                help="Run workspace selector")

    # ecc artifacts
    artifacts_parser = subparsers.add_parser("artifacts", help="List generated files")
    _add_project_arg(artifacts_parser)
    artifacts_parser.add_argument("step", nargs="?", default=None, help="Step name")
    artifacts_parser.add_argument("--json", action="store_true", help="JSON output")
    artifacts_parser.add_argument("--jsonl", action="store_true", help="JSONL output")
    artifacts_parser.add_argument("--plain", action="store_true", help="Plain key-value output")
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
    config_parser.add_argument("--plain", action="store_true", help="Plain key-value output")
    config_parser.add_argument("--run-id", default=None, dest="run_id",
                               help="Run workspace selector")

    # ecc diagnose
    diagnose_parser = subparsers.add_parser("diagnose", help="Show run diagnostics")
    _add_project_arg(diagnose_parser)
    diagnose_parser.add_argument("step", nargs="?", default=None, help="Step name")
    diagnose_parser.add_argument("--json", action="store_true", help="JSON output")
    diagnose_parser.add_argument("--jsonl", action="store_true", help="JSONL output")
    diagnose_parser.add_argument("--plain", action="store_true", help="Plain key-value output")
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


def _should_colorize():
    from chipcompiler.cli.pretty import supports_color
    return supports_color(file=sys.stdout)


def _render_log_text(args, result, color=True) -> None:
    from chipcompiler.cli.log_view import (
        render_log_listing_pretty,
        render_log_pretty,
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

    # Status/sentinel records (no_logs, empty, etc.)
    if "log_status" in first or "status" in first:
        render_generic_block(records, color=color, tag="log")
        return

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

    if "line_no" in records[0]:
        render_log_records_plain(records)
        return

    render_result(result, OutputMode.PLAIN)


def run(argv: Sequence[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]

    if _is_legacy_args(raw):
        return _run_legacy(raw)

    parser = build_parser()
    args = parser.parse_args(raw)

    if args.command is None:
        parser.print_help()
        return 1

    ctx = build_context(args)
    result = dispatch(args, ctx)

    color = _should_colorize()

    if args.command == "param" and ctx.output_mode == OutputMode.TEXT:
        _render_param_text(args, result, color=color)
    elif args.command == "log" and ctx.output_mode == OutputMode.TEXT:
        _render_log_text(args, result, color=color)
    elif args.command == "log" and ctx.output_mode == OutputMode.PLAIN:
        _render_log_plain(result)
    else:
        render_result(result, ctx.output_mode, command=args.command, color=color)

    return result.exit_code


_LEGACY_FLAGS = {"--workspace", "--rtl", "--design", "--top", "--clock", "--pdk-root", "--freq"}


def _is_legacy_args(args: list[str]) -> bool:
    for a in args:
        if a in _LEGACY_FLAGS:
            return True
        if "=" in a:
            flag = a.split("=", 1)[0]
            if flag in _LEGACY_FLAGS:
                return True
    return False


def _resolve_rtl_input(rtl_path: str) -> tuple[str, str]:
    from chipcompiler.utility.filelist import parse_filelist, validate_filelist

    normalized = os.path.abspath(os.path.expanduser(rtl_path))
    suffix = os.path.splitext(normalized)[1].lower()
    if suffix in {".f", ".fl", ".filelist"}:
        return ("", normalized)
    if suffix in {".v", ".sv", ".svh", ".vh"}:
        return (normalized, "")
    try:
        parse_filelist(normalized)
        _, missing = validate_filelist(normalized)
        if not missing:
            return ("", normalized)
    except Exception:
        pass
    return (normalized, "")


def _validate_legacy_args(args) -> str | None:
    if not str(args.workspace).strip():
        return "--workspace must not be empty"
    if not str(args.design).strip():
        return "--design must not be empty"
    if not str(args.top).strip():
        return "--top must not be empty"
    if not str(args.clock).strip():
        return "--clock must not be empty"
    rtl_path = os.path.abspath(os.path.expanduser(args.rtl))
    if not os.path.exists(rtl_path):
        return f"--rtl path does not exist: {rtl_path}"
    if not os.path.isfile(rtl_path):
        return f"--rtl must point to a file: {rtl_path}"
    pdk_root = os.path.abspath(os.path.expanduser(args.pdk_root))
    if not os.path.exists(pdk_root):
        return f"--pdk-root path does not exist: {pdk_root}"
    if not os.path.isdir(pdk_root):
        return f"--pdk-root must point to a directory: {pdk_root}"
    if args.freq <= 0:
        return "--freq must be greater than 0"
    return None


def _run_legacy(argv: list[str]) -> int:
    import argparse as _argparse

    from chipcompiler.data import create_workspace, get_parameters
    from chipcompiler.engine import EngineFlow
    from chipcompiler.rtl2gds import build_rtl2gds_flow

    parser = _argparse.ArgumentParser(
        prog="cli",
        description="Legacy parameter-only invocation (use 'ecc run' for project-based flows)",
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--rtl", required=True)
    parser.add_argument("--design", required=True)
    parser.add_argument("--top", required=True)
    parser.add_argument("--clock", required=True)
    parser.add_argument("--pdk-root", required=True)
    parser.add_argument("--freq", type=float, default=100.0)
    args = parser.parse_args(argv)

    err = _validate_legacy_args(args)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    parameters = get_parameters("ics55")
    parameters.data.update({
        "PDK": "ics55",
        "Design": args.design,
        "Top module": args.top,
        "Clock": args.clock,
        "Frequency max [MHz]": args.freq,
    })

    origin_verilog, input_filelist = _resolve_rtl_input(args.rtl)

    try:
        workspace = create_workspace(
            directory=args.workspace,
            origin_def="",
            origin_verilog=origin_verilog,
            pdk="ics55",
            parameters=parameters,
            input_filelist=input_filelist,
            pdk_root=args.pdk_root,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if workspace is None:
        print("Error: failed to create workspace", file=sys.stderr)
        return 1

    engine_flow = EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        for step, tool, state in build_rtl2gds_flow():
            engine_flow.add_step(step=step, tool=tool, state=state)

    engine_flow.create_step_workspaces()

    if not engine_flow.run_steps():
        print("Error: flow execution failed", file=sys.stderr)
        return 1

    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
