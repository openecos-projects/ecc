import os
from dataclasses import dataclass
from pathlib import Path

from chipcompiler.project.manifest import (
    CONFIG_FILENAME,
    MANIFEST_FILENAME,
    ManifestError,
    load_manifest,
)


@dataclass(frozen=True)
class CurrentLocation:
    project: str | None
    workspace: str | None


def _project_marker(root: Path) -> bool:
    return any(os.path.lexists(root / name) for name in (MANIFEST_FILENAME, CONFIG_FILENAME))


def _workspace_marker(root: Path) -> bool:
    return any(
        os.path.lexists(root / "home" / name)
        for name in ("flow.json", "params.toml", "engineering-snapshot.json", "parameters.json")
    )


def _declared_workspace(project: Path, current: Path) -> str | None:
    try:
        manifest = load_manifest(str(project))
    except ManifestError:
        return None
    return next(
        (
            entry.workspace_id
            for entry in manifest.workspaces
            if Path(entry.workspace_path) == current
        ),
        None,
    )


def resolve_current_location(
    project: str | None, workspace: str | None, *, workspace_supported: bool
) -> CurrentLocation:
    if project is not None and (workspace is not None or not workspace_supported):
        return CurrentLocation(project, workspace)
    current = Path.cwd().resolve()
    if project is not None:
        if workspace is None and workspace_supported:
            root = Path(os.path.abspath(project))
            declared = _declared_workspace(root, current)
            if declared is not None:
                return CurrentLocation(project, declared)
            if (
                not os.path.lexists(root / MANIFEST_FILENAME)
                and _workspace_marker(current)
                and current.is_relative_to(root.resolve())
                and current != root.resolve()
            ):
                return CurrentLocation(project, str(current))
        return CurrentLocation(project, workspace)
    if _project_marker(current):
        return CurrentLocation(project, workspace)
    for parent in current.parents:
        if not _project_marker(parent):
            continue
        declared = _declared_workspace(parent, current)
        if declared is not None:
            return CurrentLocation(
                str(parent), declared if workspace_supported and workspace is None else workspace
            )
        if _workspace_marker(current):
            return CurrentLocation(
                str(parent),
                str(current) if workspace_supported and workspace is None else workspace,
            )
        break
    if workspace_supported and _workspace_marker(current):
        return CurrentLocation(
            str(current.parent), str(current) if workspace is None else workspace
        )
    return CurrentLocation(project, workspace)
