#!/usr/bin/env python
"""Derive a fresh-identity Workspace copy from an existing Workspace."""

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from chipcompiler.engine.snapshot.store import (
    SNAPSHOT_FILENAME,
    STALE_SNAPSHOT_FILENAME,
    create_engineering_snapshot,
)
from chipcompiler.engine.workspace.lifecycle import (
    WorkspaceLifecycleError,
    command_retry_matches,
    workspace_command_fingerprint,
    write_workspace_command,
)
from chipcompiler.engine.workspace.paths import (
    replace_string_prefix,
    rewrite_workspace_json_paths,
)
from chipcompiler.project.runtime_processes import is_run_history_file
from chipcompiler.utility.path import path_is_within

_RUNTIME_COMMANDS_FILENAME = "runtime-commands.json"
_WORKSPACE_COMMANDS_FILENAME = "workspace-commands.json"


def publish_copied_workspace(
    source_directory: str | Path,
    target_directory: str | Path,
    *,
    command_spec: dict[str, Any],
    command_id: str = "",
    cause: str = "workspace.derived",
    blocking: bool = True,
    project_id: str = "",
    source_workspace_id: str = "",
    target_workspace_id: str = "",
    source_lock: Path | None = None,
    prepare_staged: Callable[[Path], None] | None = None,
    prepare_workspace: Callable[[Any], None] | None = None,
    rewrite_target: Callable[[Path, Path], None] | None = None,
) -> Any:
    """Copy ``source_directory`` into a staged sibling, snapshot, and atomically publish.

    Excludes source-private ``.agent`` trees, per-run ``log/`` history, and
    transient command/snapshot markers. Callers supply domain-specific hooks
    for staging preparation, flow reset, and path rewriting.
    """
    from chipcompiler.data import load_workspace
    from chipcompiler.utility.workspace_lock import workspace_lock

    source = Path(source_directory).expanduser().resolve()
    target = Path(target_directory).expanduser().resolve()
    if path_is_within(target, source):
        raise WorkspaceLifecycleError(
            "workspace_invalid", f"Target directory is inside the source Workspace: {target}"
        )

    fingerprint = workspace_command_fingerprint("derive", command_spec, None)
    lock_target = source_lock if source_lock is not None else source
    # Blocking acquisition uses a stable path order so two derives can never
    # deadlock. Non-blocking takes the source lock first so a busy source fails
    # before the target's sibling lock file is created (#400).
    locks = sorted((lock_target, target), key=str) if blocking else (lock_target, target)
    with workspace_lock(locks[0], blocking=blocking), workspace_lock(locks[1], blocking=blocking):
        _sweep_stale_staging(target)
        if target.exists():
            if command_id and command_retry_matches(target, command_id, fingerprint):
                workspace = load_workspace(target)
                if workspace is not None:
                    return workspace
            raise WorkspaceLifecycleError("workspace_exists", f"Workspace already exists: {target}")
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
        staging.rmdir()
        try:

            def ignore_source_history(path: str, names: list[str]) -> list[str]:
                directory = Path(path)
                if directory == source:
                    return [".agent"]
                if directory == source / "log":
                    return [name for name in names if is_run_history_file(name)]
                return []

            shutil.copytree(source, staging, ignore=ignore_source_history)
            home = staging / "home"
            for name in (
                STALE_SNAPSHOT_FILENAME,
                _RUNTIME_COMMANDS_FILENAME,
                _WORKSPACE_COMMANDS_FILENAME,
            ):
                (home / name).unlink(missing_ok=True)

            if prepare_staged is not None:
                prepare_staged(staging)
            workspace = load_workspace(staging)
            if workspace is None:
                raise WorkspaceLifecycleError(
                    "workspace_invalid", f"Workspace cannot be opened: {source}"
                )
            if prepare_workspace is not None:
                prepare_workspace(workspace)

            snapshot = create_engineering_snapshot(
                workspace, workspace_id=target_workspace_id or None, cause=cause
            )
            if rewrite_target is not None:
                rewrite_target(staging, target)
            if command_id:
                write_workspace_command(
                    staging,
                    command_id,
                    fingerprint,
                    snapshot["workspaceId"],
                    snapshot["workspaceRevision"],
                    metadata={
                        "operation": "derive",
                        "projectId": project_id,
                        "workspaceId": target_workspace_id,
                        "workspacePath": str(target),
                        "sourceWorkspaceId": source_workspace_id,
                        "request": command_spec,
                    },
                )
            staging.rename(target)
            try:
                derived = load_workspace(target)
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                raise
            if derived is None:
                shutil.rmtree(target, ignore_errors=True)
                raise WorkspaceLifecycleError(
                    "workspace_invalid", f"Derived Workspace cannot be opened: {target}"
                )
            return derived
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def derive_workspace(
    source_directory: str | Path,
    target_directory: str | Path,
    *,
    reset_from_step: str = "",
    through_step: str = "",
    command_id: str = "",
    cause: str = "workspace.derived",
    blocking: bool = True,
    project_id: str = "",
    source_workspace_id: str = "",
    target_workspace_id: str = "",
) -> Any:
    """Copy ``source_directory`` to ``target_directory`` under a new identity.

    The source stays read-only and byte-identical. The target receives a new
    Engineering Snapshot (target_workspace_id or a fresh ID, revision 1, ``cause``), an empty
    runtime command ledger, and no inherited workspace command records. With an
    empty ``reset_from_step`` the whole flow is prepared for a rerun; otherwise
    only the named step and its flow suffix are reset while earlier steps keep
    their Success state and artifacts.

    With ``through_step``, the ledger contains only the inclusive requested
    range, with the first step's inherited inputs frozen into ``origin/``.

    Returns the loaded derived workspace.
    """
    source = Path(source_directory).expanduser().resolve()
    target = Path(target_directory).expanduser().resolve()
    if path_is_within(target, source):
        raise WorkspaceLifecycleError(
            "workspace_invalid", f"Target directory is inside the source Workspace: {target}"
        )
    if not (source / "home" / SNAPSHOT_FILENAME).is_file():
        raise WorkspaceLifecycleError(
            "workspace_invalid", f"Workspace has no Engineering Snapshot: {source}"
        )

    command_spec = {
        "directory": str(source),
        "targetDirectory": str(target),
        "resetFromStep": reset_from_step,
        **({"throughStep": through_step} if through_step else {}),
    }

    def rewrite_target(staging: Path, published: Path) -> None:
        rewrite_workspace_json_paths(
            staging,
            lambda value: replace_string_prefix(
                replace_string_prefix(value, str(source), str(published)),
                str(staging),
                str(published),
            ),
        )

    return publish_copied_workspace(
        source,
        target,
        command_spec=command_spec,
        command_id=command_id,
        cause=cause,
        blocking=blocking,
        project_id=project_id,
        source_workspace_id=source_workspace_id,
        target_workspace_id=target_workspace_id,
        prepare_workspace=lambda ws: _prepare_derived_flow(ws, reset_from_step, through_step),
        rewrite_target=rewrite_target,
    )


def _prepare_derived_flow(workspace, reset_from_step: str, through_step: str) -> None:
    from chipcompiler.engine.workspace.reset import (
        build_flow_for_workspace,
        prepare_steps_for_rerun,
    )

    engine_flow = build_flow_for_workspace(workspace)
    if through_step:
        from chipcompiler.engine.workspace.derive_range import bound_derived_flow

        bound_derived_flow(workspace, engine_flow, reset_from_step, through_step)
        _prune_derived_checklist(workspace, engine_flow.workspace_steps)
    elif reset_from_step:
        reset_steps = _reset_step_suffix(engine_flow, reset_from_step)
        prepare_steps_for_rerun(workspace, engine_flow, reset_steps)
        _prune_derived_checklist(workspace, reset_steps)
    else:
        from chipcompiler.data import prepare_workspace_for_rerun

        prepare_workspace_for_rerun(workspace, engine_flow, preserve_user_inputs=True)


def _sweep_stale_staging(target: Path) -> None:
    """Remove staging siblings left by an interrupted derive of the same target."""
    prefix = f".{target.name}.staging-"
    for sibling in target.parent.iterdir():
        if not sibling.name.startswith(prefix) or sibling.is_symlink() or not sibling.is_dir():
            continue
        shutil.rmtree(sibling)
        Path(f"{sibling}.lock").unlink(missing_ok=True)


def _reset_step_suffix(engine_flow, reset_from_step: str) -> list:
    identity = str(reset_from_step)
    workspace_steps = list(getattr(engine_flow, "workspace_steps", []))
    index = next(
        (
            position
            for position, step in enumerate(workspace_steps)
            if str(getattr(step, "name", "")) == identity
        ),
        -1,
    )
    if index < 0:
        raise WorkspaceLifecycleError(
            "flow_step_not_found", f"Flow Step not found: {reset_from_step}"
        )
    return workspace_steps[index:]


def _prune_derived_checklist(workspace, reset_steps) -> None:
    from chipcompiler.data import Checklist, workspace_checklist_path

    path = workspace_checklist_path(getattr(workspace, "directory", None))
    if not path.is_file():
        return
    wiped = {str(getattr(step, "name", "")) for step in reset_steps}
    wiped.discard("")
    checklist = Checklist(path)
    kept = [
        item
        for item in checklist.data.get("checklist", [])
        if isinstance(item, dict) and str(item.get("step", "")) not in wiped
    ]
    checklist.replace(kept)
