import argparse
import os
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
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

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
    return os.path.join(project_dir, "runs", "default")


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
