from pathlib import Path

from chipcompiler.project.manifest import ManifestError, load_manifest
from chipcompiler.project.manifest_write import manifest_lock, update_manifest_locked
from chipcompiler.utility.workspace_lock import workspace_lock


def repair_legacy_candidate_registry(project: Path, workspace: Path) -> bool:
    try:
        manifest = load_manifest(str(project))
    except ManifestError:
        return False
    if manifest.raw.get("runtime_processes") != []:
        return False

    repaired = False

    def repair(document: dict) -> None:
        nonlocal repaired
        if document.get("runtime_processes") == []:
            document["runtime_processes"] = {}
            repaired = True

    try:
        with workspace_lock(workspace, blocking=False), manifest_lock(project):
            if not update_manifest_locked(project, repair):
                raise ValueError(f"could not repair sweep candidate runtime registry: {project}")
    except BlockingIOError as exc:
        raise ValueError(f"sweep candidate workspace is busy: {workspace}") from exc
    return repaired
