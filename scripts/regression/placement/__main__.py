"""Prepare, execute and inspect frozen placement regression batches."""

import argparse
import json
from pathlib import Path

from .prepare import prepare, prepare_workspaces
from .reports import collect, status
from .run_case import run_case
from .runner import run
from .verify import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparing = commands.add_parser("prepare", help="Freeze inputs, runtime and experiment profile")
    preparing.add_argument("--source-batch", type=Path, required=True)
    preparing.add_argument("--runtime-from", type=Path, required=True)
    preparing.add_argument("--profile", type=Path, required=True)
    preparing.add_argument("--openroad", type=Path, required=True)
    preparing.add_argument("--cases", nargs="+")
    running = commands.add_parser("run", help="Run parallel placement and external evaluations")
    running.add_argument("--jobs", type=int, default=6)
    commands.add_parser("collect", help="Regenerate JSON, CSV and Markdown tables")
    commands.add_parser("status", help="Show case stages and latest logged iterations")
    commands.add_parser("verify", help="Audit all saved completion and artifact evidence")
    worker = commands.add_parser("worker", help="Run one prepared case inside the frozen runtime")
    worker.add_argument("--case", required=True)
    commands.add_parser("prepare-workspaces", help="Prepare ECC projects inside the frozen runtime")
    for command in commands.choices.values():
        command.add_argument("--batch", type=Path, required=True)
    args = parser.parse_args()
    batch = args.batch.resolve()
    if args.command == "prepare":
        prepare(
            batch,
            args.source_batch.resolve(),
            args.runtime_from.resolve(),
            args.profile.resolve(),
            args.openroad.resolve(),
            args.cases,
        )
        result = {"status": "prepared", "batch": str(batch)}
    elif args.command == "run":
        return run(batch, args.jobs)
    elif args.command == "worker":
        run_case(batch, args.case)
        return 0
    elif args.command == "prepare-workspaces":
        prepare_workspaces(batch)
        return 0
    else:
        actions = {"collect": collect, "status": status, "verify": verify}
        result = actions[args.command](batch)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
