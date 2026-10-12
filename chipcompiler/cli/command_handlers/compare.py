from chipcompiler.cli.core.compare_inputs import CompareRunInput
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.engine.snapshot import EngineeringSnapshotError, read_engineering_snapshot_file
from chipcompiler.engine.snapshot_compare import SnapshotComparisonError, compare_snapshots


def compare_run(args: CompareRunInput, _ctx: CommandContext) -> CommandResult:
    snapshots = {}
    for role, path in (("baseline", args.baseline), ("current", args.current)):
        try:
            snapshots[role] = read_engineering_snapshot_file(path)
        except (EngineeringSnapshotError, OSError) as exc:
            return CommandResult.err(
                [error_record("snapshot_read_failed", role=role, path=path, reason=str(exc))]
            )
    try:
        comparison = compare_snapshots(snapshots["baseline"], snapshots["current"])
    except SnapshotComparisonError as exc:
        return CommandResult.err([error_record("snapshot_compare_failed", reason=str(exc))])
    comparison["baseline"]["source"] = args.baseline
    comparison["current"]["source"] = args.current
    return CommandResult.ok([{"record": "run_comparison", "status": "success", **comparison}])
