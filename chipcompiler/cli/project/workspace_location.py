"""Canonical locations for explicitly placed managed workspaces."""

import os


class WorkspacePathError(ValueError):
    """A user-supplied workspace directory cannot be used safely."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code


def canonical_explicit_workspace_path(path: str, project_dir: str) -> str:
    """Validate and canonicalize a complete workspace directory path."""
    if not os.path.isabs(path):
        raise WorkspacePathError(
            "workspace_path_not_absolute",
            "workspace path must name the complete absolute workspace directory",
        )

    canonical = os.path.realpath(path)
    project = os.path.realpath(project_dir)
    legacy_runs = os.path.realpath(os.path.join(project_dir, "runs"))
    if canonical in (project, legacy_runs):
        raise WorkspacePathError(
            "workspace_path_unsafe",
            "workspace path must not be the project or legacy runs directory",
        )

    try:
        project_is_within_workspace = os.path.commonpath((canonical, project)) == canonical
    except ValueError:
        project_is_within_workspace = False
    if project_is_within_workspace:
        raise WorkspacePathError(
            "workspace_path_unsafe",
            "workspace path must not contain the project directory",
        )

    if not os.path.lexists(canonical) and not os.path.isdir(os.path.dirname(canonical)):
        raise WorkspacePathError(
            "workspace_path_unsafe",
            "the workspace parent directory must already exist",
        )
    return canonical
