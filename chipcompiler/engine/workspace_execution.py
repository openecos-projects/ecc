"""Revision-aware changes to a workspace's flow execution preferences."""

from pathlib import Path

from chipcompiler.data.workspace.execution import declared_step_subprocess, save_step_subprocess
from chipcompiler.data.workspace.transaction import (
    WorkspaceFileTransaction,
    recover_workspace_file_transaction,
)
from chipcompiler.engine.snapshot.store import (
    SNAPSHOT_FILENAME,
    read_engineering_snapshot,
    refresh_engineering_snapshot,
)
from chipcompiler.engine.workspace.lifecycle import (
    WorkspaceLifecycleError,
    _load_committed_workspace,
    command_retry_matches,
    workspace_command_fingerprint,
    write_workspace_command,
)
from chipcompiler.utility.workspace_lock import workspace_lock


def update_workspace_execution(
    directory: str | Path,
    *,
    step_subprocess: bool,
    expected_revision: int | None = None,
    command_id: str = "",
    blocking: bool = True,
):
    """Change execution policy atomically without invalidating design results."""
    if not isinstance(step_subprocess, bool):
        raise WorkspaceLifecycleError("invalid_value", "step_subprocess must be a boolean")
    target = Path(directory).expanduser().resolve()
    if not target.is_dir():
        raise WorkspaceLifecycleError("workspace_missing", f"Workspace not found: {target}")
    fingerprint = workspace_command_fingerprint(
        "execution", {"stepSubprocess": step_subprocess}, None, expected_revision
    )
    with workspace_lock(target, blocking=blocking):
        recover_workspace_file_transaction(target)
        if command_id and command_retry_matches(target, command_id, fingerprint):
            return _load_committed_workspace(target)
        workspace = _load_committed_workspace(target)
        current = read_engineering_snapshot(workspace)
        if expected_revision is not None and current["workspaceRevision"] != expected_revision:
            raise WorkspaceLifecycleError(
                "revision_conflict",
                "Workspace Revision does not match",
                {
                    "expectedWorkspaceRevision": expected_revision,
                    "actualWorkspaceRevision": current["workspaceRevision"],
                },
            )
        changed = declared_step_subprocess(workspace.flow.data) is not step_subprocess
        paths = [
            target / "home" / "flow.json",
            target / "home" / SNAPSHOT_FILENAME,
            target / "home" / "workspace-commands.json",
        ]
        transaction = WorkspaceFileTransaction.begin(target, paths)
        try:
            if changed:
                save_step_subprocess(workspace.flow, value=step_subprocess)
                current = refresh_engineering_snapshot(
                    workspace,
                    workspace_id=current["workspaceId"],
                    cause="workspace.execution_updated",
                )
            write_workspace_command(
                target,
                command_id,
                fingerprint,
                current["workspaceId"],
                current["workspaceRevision"],
            )
            transaction.commit()
        except BaseException:
            transaction.rollback()
            raise
        return workspace
