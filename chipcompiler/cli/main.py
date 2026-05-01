import argparse
import sys
from collections.abc import Sequence

from chipcompiler.cli.config import (
    find_config_path,
    load_project_config,
    resolve_project_dir,
)


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

    # ecc status
    status_parser = subparsers.add_parser("status", help="Show run and step status")
    _add_project_arg(status_parser)
    status_parser.add_argument("--json", action="store_true", help="JSON output")
    status_parser.add_argument("--jsonl", action="store_true", help="JSONL output")

    # ecc log
    log_parser = subparsers.add_parser("log", help="Inspect step logs")
    _add_project_arg(log_parser)
    log_parser.add_argument("step", nargs="?", default=None, help="Step name")
    log_parser.add_argument("--errors", action="store_true", help="Filter error lines")
    log_parser.add_argument("--jsonl", action="store_true", help="JSONL output")

    # ecc metrics
    metrics_parser = subparsers.add_parser("metrics", help="Show step metrics")
    _add_project_arg(metrics_parser)
    metrics_parser.add_argument("step", nargs="?", default=None, help="Step name")
    metrics_parser.add_argument("--json", action="store_true", help="JSON output")
    metrics_parser.add_argument("--jsonl", action="store_true", help="JSONL output")

    return parser


def _add_project_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", default=None,
                        help="Project directory (default: current directory)")


def run(argv: Sequence[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]

    if _is_legacy_args(raw):
        return _run_legacy(raw)

    parser = build_parser()
    args = parser.parse_args(raw)

    if args.command is None:
        parser.print_help()
        return 1

    project = getattr(args, "project", None)
    project_dir = resolve_project_dir(project)

    match args.command:
        case "init":
            return _cmd_init(args)
        case "check":
            return _cmd_check(args, project_dir, project)
        case "run":
            return _cmd_run(args, project_dir, project)
        case "status":
            return _cmd_status(args, project_dir, project)
        case "log":
            return _cmd_log(args, project_dir, project)
        case "metrics":
            return _cmd_metrics(args, project_dir, project)
        case _:
            parser.print_help()
            return 1


def _cmd_init(args) -> int:
    from chipcompiler.cli.output import emit_text
    from chipcompiler.cli.project import init_project

    lines, rc = init_project(args.name, args.name)
    if lines:
        emit_text(lines)
    return rc


def _cmd_check(args, project_dir: str, project: str | None) -> int:
    from chipcompiler.cli.output import emit_json, emit_text
    from chipcompiler.cli.project import check_project

    if getattr(args, "json", False):
        config_path = find_config_path(project_dir)
        if config_path is None:
            emit_json({"status": "fail", "errors": ["missing ecc.toml"]})
            return 1
        cfg = load_project_config(config_path)
        from chipcompiler.cli.config import validate_project_config
        errors = validate_project_config(cfg)
        if errors:
            emit_json({"status": "fail", "errors": errors})
            return 1
        emit_json({
            "status": "pass",
            "design": cfg.design_name,
            "top": cfg.design_top,
            "rtl": cfg.design_rtl,
            "pdk": cfg.pdk_name,
            "preset": cfg.flow_preset,
        })
        return 0

    lines, rc = check_project(project_dir, project)
    if lines:
        emit_text(lines)
    return rc


def _cmd_run(args, project_dir: str, project: str | None) -> int:
    from chipcompiler.cli.output import emit_text
    from chipcompiler.cli.project import run_project

    lines, rc = run_project(project_dir, args.overwrite, project)
    if lines:
        emit_text(lines)
    return rc


def _cmd_status(args, project_dir: str, project: str | None) -> int:
    from chipcompiler.cli.inspect import build_status_json, build_status_jsonl, build_status_lines
    from chipcompiler.cli.output import emit_json, emit_jsonl, emit_text

    run_dir = _run_dir(project_dir)

    if getattr(args, "jsonl", False):
        objects, rc = build_status_jsonl(run_dir)
        emit_jsonl(objects)
        return rc

    if getattr(args, "json", False):
        obj, rc = build_status_json(run_dir)
        emit_json(obj)
        return rc

    lines, rc = build_status_lines(run_dir, project)
    emit_text(lines)
    return rc


def _cmd_log(args, project_dir: str, project: str | None) -> int:
    from chipcompiler.cli.inspect import build_log_jsonl, build_log_lines
    from chipcompiler.cli.output import emit_jsonl, emit_text

    run_dir = _run_dir(project_dir)

    if getattr(args, "jsonl", False):
        objects, rc = build_log_jsonl(run_dir, args.step, args.errors, project)
        emit_jsonl(objects)
        return rc

    lines, rc = build_log_lines(run_dir, args.step, args.errors, project)
    emit_text(lines)
    return rc


def _cmd_metrics(args, project_dir: str, project: str | None) -> int:
    from chipcompiler.cli.inspect import (
        build_metrics_json,
        build_metrics_jsonl,
        build_metrics_lines,
    )
    from chipcompiler.cli.output import emit_json, emit_jsonl, emit_text

    run_dir = _run_dir(project_dir)

    if getattr(args, "jsonl", False):
        objects, rc = build_metrics_jsonl(run_dir, args.step, project)
        emit_jsonl(objects)
        return rc

    if getattr(args, "json", False):
        obj, rc = build_metrics_json(run_dir, args.step, project)
        emit_json(obj)
        return rc

    lines, rc = build_metrics_lines(run_dir, args.step, project)
    emit_text(lines)
    return rc


def _run_dir(project_dir: str) -> str:
    import os
    return os.path.join(project_dir, "runs", "default")


_LEGACY_FLAGS = {"--workspace", "--rtl", "--design", "--top", "--clock", "--pdk-root", "--freq"}


def _is_legacy_args(args: list[str]) -> bool:
    return any(a in _LEGACY_FLAGS for a in args)


def _run_legacy(argv: list[str]) -> int:
    import argparse

    from chipcompiler.data import create_workspace, get_parameters
    from chipcompiler.engine import EngineFlow
    from chipcompiler.rtl2gds import build_rtl2gds_flow

    parser = argparse.ArgumentParser(
        prog="ecc",
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

    parameters = get_parameters("ics55")
    parameters.data.update({
        "PDK": "ics55",
        "Design": args.design,
        "Top module": args.top,
        "Clock": args.clock,
        "Frequency max [MHz]": args.freq,
    })

    try:
        workspace = create_workspace(
            directory=args.workspace,
            origin_def="",
            origin_verilog=args.rtl,
            pdk="ics55",
            parameters=parameters,
            input_filelist="",
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
