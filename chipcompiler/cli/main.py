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
    status_parser.add_argument("--run-id", default=None, dest="run_id",
                               help="Run workspace selector")

    # ecc log
    log_parser = subparsers.add_parser("log", help="Inspect step logs")
    _add_project_arg(log_parser)
    log_parser.add_argument("step", nargs="?", default=None, help="Step name")
    log_parser.add_argument("--errors", action="store_true", help="Filter error lines")
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
        case "artifacts":
            return _cmd_artifacts(args, project_dir, project)
        case "config":
            return _cmd_config(args, project_dir, project)
        case "diagnose":
            return _cmd_diagnose(args, project_dir, project)
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

    run_dir, run_id = _resolve_run(project_dir, getattr(args, "run_id", None))

    if getattr(args, "jsonl", False):
        objects, rc = build_status_jsonl(run_dir, run_id)
        emit_jsonl(objects)
        return rc

    if getattr(args, "json", False):
        obj, rc = build_status_json(run_dir, run_id)
        emit_json(obj)
        return rc

    lines, rc = build_status_lines(run_dir, project, run_id)
    emit_text(lines)
    return rc


def _cmd_log(args, project_dir: str, project: str | None) -> int:
    from chipcompiler.cli.inspect import build_log_jsonl, build_log_lines
    from chipcompiler.cli.output import emit_jsonl, emit_text

    run_dir, run_id = _resolve_run(project_dir, getattr(args, "run_id", None))

    if getattr(args, "jsonl", False):
        objects, rc = build_log_jsonl(run_dir, args.step, args.errors, project, run_id)
        emit_jsonl(objects)
        return rc

    lines, rc = build_log_lines(run_dir, args.step, args.errors, project, run_id)
    emit_text(lines)
    return rc


def _cmd_metrics(args, project_dir: str, project: str | None) -> int:
    from chipcompiler.cli.inspect import (
        build_metrics_json,
        build_metrics_jsonl,
        build_metrics_lines,
    )
    from chipcompiler.cli.output import emit_json, emit_jsonl, emit_text

    run_dir, run_id = _resolve_run(project_dir, getattr(args, "run_id", None))

    if getattr(args, "jsonl", False):
        objects, rc = build_metrics_jsonl(run_dir, args.step, project, run_id)
        emit_jsonl(objects)
        return rc

    if getattr(args, "json", False):
        obj, rc = build_metrics_json(run_dir, args.step, project, run_id)
        emit_json(obj)
        return rc

    lines, rc = build_metrics_lines(run_dir, args.step, project, run_id)
    emit_text(lines)
    return rc


def _cmd_artifacts(args, project_dir: str, project: str | None) -> int:
    from chipcompiler.cli.artifacts import (
        build_artifacts_json,
        build_artifacts_jsonl,
        build_artifacts_lines,
    )
    from chipcompiler.cli.output import emit_json, emit_jsonl, emit_text

    run_dir, run_id = _resolve_run(project_dir, getattr(args, "run_id", None))

    if getattr(args, "jsonl", False):
        objects, rc = build_artifacts_jsonl(run_dir, args.step, project, run_id, project_dir)
        emit_jsonl(objects)
        return rc

    if getattr(args, "json", False):
        obj, rc = build_artifacts_json(run_dir, args.step, project, run_id, project_dir)
        emit_json(obj)
        return rc

    lines, rc = build_artifacts_lines(run_dir, args.step, project, run_id, project_dir)
    emit_text(lines)
    return rc


def _cmd_config(args, project_dir: str, project: str | None) -> int:
    from chipcompiler.cli.config_view import (
        build_config_json,
        build_config_jsonl,
        build_config_lines,
        build_project_config_items,
        build_step_config_items,
    )
    from chipcompiler.cli.output import emit_json, emit_jsonl, emit_text

    run_dir, run_id = _resolve_run(project_dir, getattr(args, "run_id", None))

    if args.step is not None:
        items, rc = build_step_config_items(run_dir, args.step, project, run_id, project_dir)
    else:
        items, rc = build_project_config_items(project_dir, run_dir, project, run_id)

    if getattr(args, "jsonl", False):
        objects, rc = build_config_jsonl(items)
        emit_jsonl(objects)
        return rc

    if getattr(args, "json", False):
        obj, rc = build_config_json(items)
        emit_json(obj)
        return rc

    lines, rc = build_config_lines(items, project, run_id)
    if lines:
        emit_text(lines)
    return rc


def _cmd_diagnose(args, project_dir: str, project: str | None) -> int:
    from chipcompiler.cli.diagnose import (
        build_diagnose_json,
        build_diagnose_jsonl,
        build_diagnose_lines,
    )
    from chipcompiler.cli.output import emit_json, emit_jsonl, emit_text

    run_dir, run_id = _resolve_run(project_dir, getattr(args, "run_id", None))

    if getattr(args, "jsonl", False):
        objects, rc = build_diagnose_jsonl(run_dir, args.step, project, run_id)
        emit_jsonl(objects)
        return rc

    if getattr(args, "json", False):
        obj, rc = build_diagnose_json(run_dir, args.step, project, run_id)
        emit_json(obj)
        return rc

    lines, rc = build_diagnose_lines(run_dir, args.step, project, run_id)
    if lines:
        emit_text(lines)
    return rc


def _resolve_run(project_dir: str, run_id: str | None = None) -> tuple[str, str | None]:
    from chipcompiler.cli.inspect import resolve_run_dir
    return resolve_run_dir(project_dir, run_id)


def _run_dir(project_dir: str) -> str:
    return os.path.join(project_dir, "runs", "default")


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
