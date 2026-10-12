from chipcompiler.cli.core.records import error_record, manifest_error_record
from chipcompiler.cli.core.snapshot_inputs import ReportSnapshotInput
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.inspection.discovery import resolve_workspace_path
from chipcompiler.engine.snapshot import EngineeringSnapshotError
from chipcompiler.engine.snapshot_export import SnapshotDestinationError, save_engineering_snapshot


def snapshot(command_input: ReportSnapshotInput, ctx: CommandContext) -> CommandResult:
    if ctx.manifest_error:
        return CommandResult.err([manifest_error_record(ctx.manifest_error)])
    workspace_dir, failure = resolve_workspace_path(
        command_input.workspace, ctx.project, ctx.run_id, ctx.run_dir
    )
    if failure is not None:
        return CommandResult.err([failure])
    try:
        saved = save_engineering_snapshot(workspace_dir, command_input.output_path)
    except EngineeringSnapshotError as exc:
        return CommandResult.err([error_record("snapshot_read_failed", reason=str(exc))])
    except SnapshotDestinationError as exc:
        return CommandResult.err(
            [
                error_record(
                    "report_destination_invalid", path=command_input.output_path, reason=str(exc)
                )
            ]
        )
    except FileExistsError as exc:
        return CommandResult.err(
            [
                error_record(
                    "report_destination_exists", path=command_input.output_path, reason=str(exc)
                )
            ]
        )
    except OSError as exc:
        return CommandResult.err(
            [error_record("report_write_failed", path=command_input.output_path, reason=str(exc))]
        )
    return CommandResult.ok(
        [
            {
                "report": "snapshot",
                "path": str(saved.path),
                "source": str(saved.source),
                "bytes": saved.bytes_written,
                "schema_version": saved.schema_version,
                "workspace_id": saved.workspace_id,
                "workspace_revision": saved.workspace_revision,
                "status": "written",
            }
        ]
    )
