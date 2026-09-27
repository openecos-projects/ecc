"""Run-lifecycle status write-back into the owning project manifest.

The CLI records the run lifecycle in project.json (``running``, then the
terminal status) so manifest readers never see a stale status. Runtime-driven
runs (``flow_run`` / ``flow_run_step`` and their operation wrappers) get the
same behavior here. The terminal write-back also re-converges the entry's
other derived fields (range, parameter_patch) on the directory — a run
writes back computed geometry. An in-place workspace update similarly
refreshes the entry's derived fields from the workspace directory, and a
retaining update registers the kept replace-backup directory as an archived
entry; baseline/best pointers at the replaced generation then follow the
registered backup entry, or clear when no backup was retained. Workspaces outside a manifest project
are skipped, and every failure degrades to a log warning — the write-back
never fails the triggering operation.
"""

import logging
from contextlib import contextmanager
from pathlib import Path

from chipcompiler.runtime.operations import RuntimeOperationCancelled

logger = logging.getLogger(__name__)


def write_back_workspace_run_status(workspace_directory: str | Path, status: str) -> None:
    """Best-effort project.json status write-back for a managed workspace."""
    from chipcompiler.project import discover_project_manifest
    from chipcompiler.project.manifest_write import write_back_workspace_status

    directory = Path(workspace_directory).expanduser().resolve()
    try:
        discovered = discover_project_manifest(directory)
    except (OSError, ValueError) as exc:
        logger.warning("manifest discovery failed: %s: %s", directory, exc)
        return
    if discovered is None:
        return
    project_dir, manifest = discovered
    workspace_id = _registered_workspace_id(project_dir, manifest, directory)
    if workspace_id is None:
        return
    if not write_back_workspace_status(str(project_dir), workspace_id, status):
        logger.warning(
            "manifest write-back failed: %s: %s -> %s", project_dir, workspace_id, status
        )


def write_back_workspace_derived_fields(
    workspace_directory: str | Path, *, include_status: bool = True
) -> None:
    """Best-effort derived-field refresh after an in-place workspace update.

    The owning project manifest entry's derived fields re-converge on the
    workspace directory's facts under the project lock; workspaces outside a
    manifest project are skipped. ``include_status=False`` is for the run
    terminal-writeback path, where status stays with the explicit write-back.
    """
    from chipcompiler.project import discover_project_manifest
    from chipcompiler.project.manifest_refresh import refresh_workspace_derived_fields

    directory = Path(workspace_directory).expanduser().resolve()
    try:
        discovered = discover_project_manifest(directory)
    except (OSError, ValueError) as exc:
        logger.warning("manifest discovery failed: %s: %s", directory, exc)
        return
    if discovered is None:
        return
    project_dir, manifest = discovered
    workspace_id = _registered_workspace_id(project_dir, manifest, directory)
    if workspace_id is None:
        return
    if not refresh_workspace_derived_fields(
        str(project_dir), workspace_id, include_status=include_status
    ):
        logger.warning("manifest derived-field refresh failed: %s: %s", project_dir, workspace_id)


def register_replace_backup_workspace(
    workspace_directory: str | Path,
    backup_directory: str | Path,
) -> None:
    """Best-effort archived manifest registration of a retained replace backup.

    The owning project is discovered from the (already updated) workspace
    directory; the backup entry's lineage points at the workspace's manifest
    id. Standalone workspaces are skipped, and every failure degrades to a
    log warning — registration never fails the committed update.
    """
    from chipcompiler.project import discover_project_manifest, register_workspace_backup

    directory = Path(workspace_directory).expanduser().resolve()
    backup = Path(backup_directory).expanduser().resolve()
    try:
        discovered = discover_project_manifest(directory)
    except (OSError, ValueError) as exc:
        logger.warning("manifest discovery failed: %s: %s", directory, exc)
        return
    if discovered is None:
        logger.warning("replace backup not registered (no owning project): %s", backup)
        return
    project_dir, manifest = discovered
    workspace_id = _registered_workspace_id(project_dir, manifest, directory)
    if workspace_id is None:
        logger.warning("replace backup not registered (workspace not in manifest): %s", backup)
        return
    try:
        register_workspace_backup(project_dir, backup, source_workspace_id=workspace_id)
    except (OSError, ValueError) as exc:
        logger.warning("replace backup registration failed: %s: %s", backup, exc)


def repoint_generation_pointers_after_update(
    workspace_directory: str | Path,
    backup_directory: str | Path | None,
) -> None:
    """Best-effort baseline/best pointer maintenance after an in-place update.

    Pointers at the replaced workspace's manifest id follow the registered
    archived backup entry, or clear when no backup was retained. Standalone
    workspaces are skipped, and every failure degrades to a log warning.
    """
    from chipcompiler.project import discover_project_manifest, repoint_generation_pointers

    directory = Path(workspace_directory).expanduser().resolve()
    try:
        discovered = discover_project_manifest(directory)
    except (OSError, ValueError) as exc:
        logger.warning("manifest discovery failed: %s: %s", directory, exc)
        return
    if discovered is None:
        return
    project_dir, manifest = discovered
    workspace_id = _registered_workspace_id(project_dir, manifest, directory)
    if workspace_id is None:
        return
    backup_workspace_id = (
        Path(backup_directory).expanduser().resolve().name if backup_directory is not None else None
    )
    try:
        repoint_generation_pointers(project_dir, workspace_id, backup_workspace_id)
    except (OSError, ValueError) as exc:
        logger.warning("generation pointer repoint failed: %s: %s", project_dir, exc)


@contextmanager
def manifest_run_status(workspace_directory: str | Path):
    """Track one run in project.json: running, then a terminal status.

    A cancelled run leaves partial progress, which maps to ``in_progress``;
    any other failure maps to ``failed`` — a workspace never stays ``running``
    after the run ends, mirroring the CLI contract. At each terminal exit the
    entry's other derived fields (range, parameter_patch) re-converge on the
    directory first — a run writes back computed geometry — while status
    stays with the explicit write-backs below.
    """
    write_back_workspace_run_status(workspace_directory, "running")
    try:
        yield
    except RuntimeOperationCancelled:
        write_back_workspace_derived_fields(workspace_directory, include_status=False)
        write_back_workspace_run_status(workspace_directory, "in_progress")
        raise
    except Exception:
        write_back_workspace_derived_fields(workspace_directory, include_status=False)
        write_back_workspace_run_status(workspace_directory, "failed")
        raise
    else:
        write_back_workspace_derived_fields(workspace_directory, include_status=False)
        write_back_workspace_run_status(workspace_directory, "success")


def _registered_workspace_id(project_dir: Path, manifest: dict, directory: Path) -> str | None:
    """Return the manifest workspace_id for *directory*, or None when the
    discovered project does not actually register this workspace (an unrelated
    ancestor project.json must not collect status write-backs)."""
    for entry in manifest.get("workspaces", []):
        if not isinstance(entry, dict):
            continue
        workspace_path = entry.get("workspace_path")
        if not isinstance(workspace_path, str) or not workspace_path.strip():
            continue
        candidate = Path(workspace_path).expanduser()
        if not candidate.is_absolute():
            candidate = project_dir / candidate
        if candidate.resolve() == directory:
            workspace_id = entry.get("workspace_id")
            return workspace_id if isinstance(workspace_id, str) and workspace_id else None
    return None
