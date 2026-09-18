"""Run-lifecycle status write-back into the owning project manifest.

The CLI records the run lifecycle in project.json (``running``, then the
terminal status) so manifest readers never see a stale status. Runtime-driven
runs (``flow_run`` / ``flow_run_step`` and their operation wrappers) get the
same behavior here. Workspaces outside a manifest project are skipped, and
every failure degrades to a log warning — the write-back never fails a run.
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


@contextmanager
def manifest_run_status(workspace_directory: str | Path):
    """Track one run in project.json: running, then a terminal status.

    A cancelled run leaves partial progress, which maps to ``in_progress``;
    any other failure maps to ``failed`` — a workspace never stays ``running``
    after the run ends, mirroring the CLI contract.
    """
    write_back_workspace_run_status(workspace_directory, "running")
    try:
        yield
    except RuntimeOperationCancelled:
        write_back_workspace_run_status(workspace_directory, "in_progress")
        raise
    except Exception:
        write_back_workspace_run_status(workspace_directory, "failed")
        raise
    else:
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
