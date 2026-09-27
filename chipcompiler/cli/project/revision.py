"""Workspace revision compare-and-swap helpers for CLI mutations."""

from pathlib import Path

from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandResult
from chipcompiler.engine.snapshot import (
    EngineeringSnapshotError,
    read_engineering_snapshot_from_directory,
)


def expected_revision_error(
    workspace: str | Path,
    expected_revision: int | None,
    *,
    workspace_id: str | None = None,
) -> CommandResult | None:
    """Return exit 21 when the locked Workspace revision does not match."""
    if expected_revision is None:
        return None
    try:
        snapshot = read_engineering_snapshot_from_directory(workspace)
        actual_revision: int | None = snapshot["workspaceRevision"]
    except (EngineeringSnapshotError, OSError):
        actual_revision = None
    if actual_revision == expected_revision:
        return None
    return CommandResult.err(
        [
            error_record(
                "revision_conflict",
                workspace_id=workspace_id,
                workspace=str(workspace),
                expected_revision=expected_revision,
                actual_revision=actual_revision,
            )
        ],
        exit_code=21,
    )
