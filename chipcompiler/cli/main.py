import argparse
import sys
from collections.abc import Sequence

from chipcompiler.cli.commands import build_context, dispatch
from chipcompiler.cli.render import render_result


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

    ctx = build_context(args)
    result = dispatch(args, ctx)
    render_result(result, ctx.output_mode)
    return result.exit_code


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
