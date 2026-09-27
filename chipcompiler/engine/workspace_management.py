"""Managed Workspace archive and deletion transactions."""

import json
import re
import shutil
from pathlib import Path

from chipcompiler.engine.reconcile import _workspace_lock
from chipcompiler.engine.snapshot import read_engineering_snapshot_from_directory
from chipcompiler.engine.workspace_lifecycle import (
    WorkspaceLifecycleError,
    _workspace_command_fingerprint,
    _write_workspace_command,
)
from chipcompiler.project.api import _project_manifest_mutator
from chipcompiler.project.manifest import load_manifest
from chipcompiler.project.manifest_write import manifest_lock, update_manifest_locked

_COMMAND_ID = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
_DELETE_STAGING_PREFIX = ".ecc-delete-"


def archive_managed_workspace(
    project_dir: str | Path,
    workspace_id: str,
    expected_revision: int,
    *,
    command_id: str,
    blocking: bool,
) -> Path:
    project = Path(project_dir).expanduser().resolve()
    workspace = _manifest_workspace_path(project, workspace_id)
    fingerprint = _workspace_command_fingerprint(
        "archive", {"project": str(project), "workspaceId": workspace_id}, {}, expected_revision
    )
    with _workspace_lock(workspace, blocking=blocking):
        snapshot = _check_revision(workspace, expected_revision)
        with manifest_lock(project, blocking=blocking):
            manifest = load_manifest(str(project))
            entry = _require_entry(manifest, workspace_id, workspace)
            _reject_running(manifest.raw, workspace_id)
            if entry.status != "archived" and not update_manifest_locked(
                project,
                _project_manifest_mutator(
                    project, {"type": "archive_workspace", "workspace_id": workspace_id}
                ),
            ):
                raise WorkspaceLifecycleError(
                    "project_manifest_update_failed", "Project Manifest update failed"
                )
        _write_workspace_command(
            workspace,
            command_id,
            fingerprint,
            snapshot["workspaceId"],
            snapshot["workspaceRevision"],
        )
    return workspace


def delete_managed_workspace(
    project_dir: str | Path,
    workspace_id: str,
    expected_revision: int,
    *,
    command_id: str,
    delete_directory: bool,
    blocking: bool,
) -> Path:
    project = Path(project_dir).expanduser().resolve()
    workspace = _manifest_workspace_path(project, workspace_id)
    if not command_id or not _COMMAND_ID.fullmatch(command_id):
        raise WorkspaceLifecycleError(
            "invalid_command_id", "Workspace delete requires a safe command ID"
        )
    fingerprint = _workspace_command_fingerprint(
        "delete",
        {
            "project": str(project),
            "workspaceId": workspace_id,
            "workspace": str(workspace),
            "deleteDirectory": delete_directory,
        },
        {},
        expected_revision,
    )
    staging = project / f".ecc-delete-{workspace_id}-{command_id}"
    with _workspace_lock(workspace, blocking=blocking):
        snapshot = _check_revision(workspace, expected_revision)
        if delete_directory:
            _validate_deletable_workspace(project, workspace, staging)
            _write_workspace_command(
                workspace,
                command_id,
                fingerprint,
                snapshot["workspaceId"],
                snapshot["workspaceRevision"],
                metadata={
                    "operation": "delete",
                    "projectId": load_manifest(str(project)).project_id,
                    "workspaceId": workspace_id,
                    "workspacePath": str(workspace),
                    "phase": "intent",
                },
            )
            workspace.rename(staging)
        try:
            with manifest_lock(project, blocking=blocking):
                manifest = load_manifest(str(project))
                _require_entry(manifest, workspace_id, workspace)
                _reject_running(manifest.raw, workspace_id)
                if not update_manifest_locked(
                    project,
                    _project_manifest_mutator(
                        project, {"type": "delete_workspace", "workspace_id": workspace_id}
                    ),
                ):
                    raise WorkspaceLifecycleError(
                        "project_manifest_update_failed", "Project Manifest update failed"
                    )
        except BaseException:
            if delete_directory and staging.is_dir() and not workspace.exists():
                staging.rename(workspace)
            raise
        if not delete_directory:
            _write_workspace_command(
                workspace,
                command_id,
                fingerprint,
                snapshot["workspaceId"],
                snapshot["workspaceRevision"],
            )
    if delete_directory:
        shutil.rmtree(staging)
    return workspace


def reconcile_workspace_deletes(
    project_dir: str | Path, *, blocking: bool
) -> tuple[str, ...]:
    """Recover proven interrupted destructive deletes in the Project root."""
    project = Path(project_dir).expanduser().resolve()
    manifest = load_manifest(str(project))
    candidates = []
    for candidate in project.iterdir():
        if not candidate.name.startswith(_DELETE_STAGING_PREFIX):
            continue
        candidates.append(_validate_delete_staging(project, manifest.project_id, candidate))
    original_paths = [proof["original"] for proof in candidates]
    if len(set(original_paths)) != len(original_paths):
        raise WorkspaceLifecycleError(
            "workspace_delete_recovery_ambiguous",
            "Multiple delete staging directories claim the same Workspace",
        )
    recovered: list[str] = []
    for proof in candidates:
        original = proof["original"]
        staging = proof["staging"]
        workspace_id = proof["workspace_id"]
        with _workspace_lock(original, blocking=blocking):
            with manifest_lock(project, blocking=blocking):
                current = load_manifest(str(project))
                entry = current.find_workspace(workspace_id)
                if entry is not None:
                    if Path(entry.workspace_path).resolve() != original:
                        raise WorkspaceLifecycleError(
                            "workspace_identity_changed",
                            "Workspace registration changed during delete recovery",
                        )
                    if original.exists() or original.is_symlink():
                        raise WorkspaceLifecycleError(
                            "workspace_delete_recovery_ambiguous",
                            "Both the Workspace target and delete staging exist",
                        )
                    staging.rename(original)
                    recovered.append(f"restored:{workspace_id}")
                    continue
                _reject_runtime_key(current.raw, workspace_id)
            shutil.rmtree(staging)
            recovered.append(f"removed:{workspace_id}")
    return tuple(recovered)


def _validate_delete_staging(project: Path, project_id: str, staging: Path) -> dict:
    if staging.parent != project or staging.is_symlink() or not staging.is_dir():
        raise WorkspaceLifecycleError(
            "workspace_delete_recovery_unsafe",
            f"Delete staging is not a direct, non-symlink directory: {staging}",
        )
    ledger_path = staging / "home" / "workspace-commands.json"
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WorkspaceLifecycleError(
            "workspace_delete_recovery_unproven", f"Invalid delete command ledger: {staging}"
        ) from exc
    commands = ledger.get("commands") if isinstance(ledger, dict) else None
    if (
        not isinstance(ledger, dict)
        or ledger.get("schemaVersion") != 1
        or not isinstance(commands, dict)
    ):
        raise WorkspaceLifecycleError(
            "workspace_delete_recovery_unproven", f"Invalid delete command ledger: {staging}"
        )
    matching = []
    for command_id, record in commands.items():
        metadata = record.get("metadata") if isinstance(record, dict) else None
        if (
            isinstance(command_id, str)
            and _COMMAND_ID.fullmatch(command_id)
            and isinstance(metadata, dict)
            and metadata.get("operation") == "delete"
            and metadata.get("phase") == "intent"
            and staging.name
            == f"{_DELETE_STAGING_PREFIX}{metadata.get('workspaceId')}-{command_id}"
        ):
            matching.append((command_id, record, metadata))
    if len(matching) != 1:
        raise WorkspaceLifecycleError(
            "workspace_delete_recovery_unproven",
            f"Delete staging has no unique matching intent: {staging}",
        )
    command_id, record, metadata = matching[0]
    workspace_id = metadata.get("workspaceId")
    original_text = metadata.get("workspacePath")
    if (
        metadata.get("projectId") != project_id
        or not isinstance(workspace_id, str)
        or not workspace_id
        or not isinstance(original_text, str)
    ):
        raise WorkspaceLifecycleError(
            "workspace_delete_recovery_unproven", "Delete intent identity does not match"
        )
    original = Path(original_text).resolve()
    if original.parent != project or original == project or original.name != workspace_id:
        raise WorkspaceLifecycleError(
            "workspace_delete_recovery_unsafe", "Delete intent path is outside the Project"
        )
    snapshot = read_engineering_snapshot_from_directory(staging)
    result = record.get("result") if isinstance(record, dict) else None
    expected_fingerprint = _workspace_command_fingerprint(
        "delete",
        {
            "project": str(project),
            "workspaceId": workspace_id,
            "workspace": str(original),
            "deleteDirectory": True,
        },
        {},
        snapshot["workspaceRevision"],
    )
    if (
        not isinstance(result, dict)
        or result.get("workspaceId") != snapshot["workspaceId"]
        or result.get("workspaceRevision") != snapshot["workspaceRevision"]
        or record.get("fingerprint") != expected_fingerprint
    ):
        raise WorkspaceLifecycleError(
            "workspace_delete_recovery_unproven", "Delete intent fingerprint does not match"
        )
    return {
        "command_id": command_id,
        "workspace_id": workspace_id,
        "original": original,
        "staging": staging,
    }


def _reject_runtime_key(document: dict, workspace_id: str) -> None:
    processes = document.get("runtime_processes", {})
    if isinstance(processes, dict) and workspace_id in processes:
        raise WorkspaceLifecycleError(
            "workspace_running", "Deleted Workspace still has a registered runtime process"
        )


def _manifest_workspace_path(project: Path, workspace_id: str) -> Path:
    manifest = load_manifest(str(project))
    entry = manifest.find_workspace(workspace_id)
    if entry is None:
        raise WorkspaceLifecycleError(
            "workspace_not_declared", f"Workspace is not registered: {workspace_id}"
        )
    return Path(entry.workspace_path).resolve()


def _require_entry(manifest, workspace_id: str, expected_path: Path):
    entry = manifest.find_workspace(workspace_id)
    if entry is None or Path(entry.workspace_path).resolve() != expected_path:
        raise WorkspaceLifecycleError(
            "workspace_identity_changed", "Workspace registration changed while locked"
        )
    return entry


def _reject_running(document: dict, workspace_id: str) -> None:
    processes = document.get("runtime_processes", {})
    if isinstance(processes, dict) and workspace_id in processes:
        raise WorkspaceLifecycleError(
            "workspace_running", "Workspace has a registered runtime process"
        )


def _check_revision(workspace: Path, expected_revision: int) -> dict:
    snapshot = read_engineering_snapshot_from_directory(workspace)
    if snapshot["workspaceRevision"] != expected_revision:
        raise WorkspaceLifecycleError(
            "revision_conflict",
            "Workspace Revision does not match",
            {
                "expectedWorkspaceRevision": expected_revision,
                "actualWorkspaceRevision": snapshot["workspaceRevision"],
            },
        )
    return snapshot


def _validate_deletable_workspace(project: Path, workspace: Path, staging: Path) -> None:
    if (
        workspace.parent != project
        or workspace == project
        or workspace.is_symlink()
        or not workspace.is_dir()
    ):
        raise WorkspaceLifecycleError(
            "workspace_delete_unsafe",
            "Only a direct, non-symlink Workspace inside the Project may be deleted",
        )
    if staging.exists() or staging.is_symlink():
        raise WorkspaceLifecycleError(
            "workspace_delete_recovery_required", f"Delete staging already exists: {staging}"
        )
