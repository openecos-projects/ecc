import sys
import tarfile
from pathlib import Path, PurePosixPath

from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.inspection.discovery import resolve_loaded_workspace, workspace_display

_MAX_ADDITIONAL_TOTAL = 64 * 1024 * 1024
_MAX_ADDITIONAL_FILE = 16 * 1024 * 1024
_MAX_ADDITIONAL_ENTRIES = 256


def inspect(command_input, ctx: CommandContext) -> CommandResult:
    workspace, failure = resolve_loaded_workspace(command_input, ctx)
    if failure is not None:
        return failure

    from chipcompiler.engine.signoff_export import inspect_signoff_package

    review = inspect_signoff_package(workspace)
    project = ctx.project
    records = [
        {
            "signoff": "inspect",
            "status": review.get("status", "blocked"),
            "workspace": workspace_display(command_input, ctx),
            "export": disclosure_cmd("ecc signoff export -o <path>", project, ctx.run_id),
            "report": disclosure_cmd("ecc report summary", project, ctx.run_id),
        }
    ]
    for group in review.get("groups", []):
        records.append(
            {
                "group": group.get("id", ""),
                "label": group.get("label", ""),
                "status": group.get("status", ""),
                "available": group.get("available"),
                "expected": group.get("expected"),
                "summary": group.get("summary"),
            }
        )
    for risk in review.get("risks", []):
        record = {
            "risk": risk.get("severity", ""),
            "title": risk.get("title", ""),
            "summary": risk.get("summary", ""),
        }
        details = risk.get("details") or []
        if details:
            first = details[0]
            record["location"] = first.get("location", "")
            record["reason"] = first.get("reason", "")
            record["detail_count"] = len(details)
        records.append(record)

    # Inspection is advisory: blocked readiness is data, not a command failure.
    return CommandResult.ok(records)


def export(command_input, ctx: CommandContext) -> CommandResult:
    try:
        additional_files = _read_additional_files(command_input.additional_files)
    except (OSError, tarfile.TarError, UnicodeDecodeError, ValueError) as exc:
        return CommandResult.err(
            [error_record("invalid_additional_files", reason=str(exc))]
        )

    try:
        from chipcompiler.engine.reconcile import _workspace_lock
        from chipcompiler.engine.signoff_export import (
            SignoffExportError,
            export_signoff_package_archive,
        )
        from chipcompiler.engine.snapshot import read_engineering_snapshot_from_directory

        with _workspace_lock(Path(ctx.run_dir), blocking=not command_input.no_wait):
            workspace, failure = resolve_loaded_workspace(command_input, ctx)
            if failure is not None:
                return failure
            if command_input.expected_revision is not None:
                current = read_engineering_snapshot_from_directory(ctx.run_dir)
                if current["workspaceRevision"] != command_input.expected_revision:
                    return CommandResult.err(
                        [
                            error_record(
                                "revision_conflict",
                                expected_revision=command_input.expected_revision,
                                actual_revision=current["workspaceRevision"],
                            )
                        ],
                        exit_code=21,
                    )
            output_path = export_signoff_package_archive(
                workspace,
                command_input.output_path,
                additional_files,
                include_debug=command_input.include_debug,
            )
    except BlockingIOError:
        return CommandResult.err([error_record("workspace_busy")], exit_code=20)
    except SignoffExportError as exc:
        return CommandResult.err(
            [
                error_record(
                    "signoff_incomplete",
                    reason=str(exc),
                    inspect=disclosure_cmd("ecc signoff inspect", ctx.project, ctx.run_id),
                )
            ]
        )
    except OSError as exc:
        # An unwritable destination, a directory in place of the output
        # path, or a full disk is a failed export, never a traceback.
        return CommandResult.err(
            [
                error_record(
                    "signoff_export_failed",
                    reason=str(exc),
                    inspect=disclosure_cmd("ecc signoff inspect", ctx.project, ctx.run_id),
                )
            ]
        )
    return CommandResult.ok(
        [
            {
                "signoff": "export",
                "status": "exported",
                "path": output_path,
                "inspect_cmd": disclosure_cmd("ecc signoff inspect", ctx.project, ctx.run_id),
            }
        ]
    )


def _read_additional_files(source: str | None) -> list[dict[str, str]] | None:
    if source is None:
        return None
    if source != "-":
        raise ValueError("--additional-files only accepts '-' for a stdin tar stream")
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    result: list[dict[str, str]] = []
    names: set[str] = set()
    total = 0
    with tarfile.open(fileobj=stream, mode="r|*") as archive:
        for member in archive:
            if len(result) >= _MAX_ADDITIONAL_ENTRIES:
                raise ValueError("additional-files tar has too many entries")
            if not member.isfile():
                raise ValueError(f"additional-files entry is not a regular file: {member.name}")
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or not path.parts
                or any(part in {"", ".", ".."} for part in path.parts)
            ):
                raise ValueError(f"invalid additional-files path: {member.name}")
            name = path.as_posix()
            if name in names:
                raise ValueError(f"duplicate additional-files path: {name}")
            if member.size < 0 or member.size > _MAX_ADDITIONAL_FILE:
                raise ValueError(f"additional-files entry is too large: {name}")
            total += member.size
            if total > _MAX_ADDITIONAL_TOTAL:
                raise ValueError("additional-files tar exceeds the total size limit")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"cannot read additional-files entry: {name}")
            payload = extracted.read(_MAX_ADDITIONAL_FILE + 1)
            if len(payload) != member.size:
                raise ValueError(f"truncated additional-files entry: {name}")
            result.append({"archivePath": name, "content": payload.decode("utf-8")})
            names.add(name)
    return result
