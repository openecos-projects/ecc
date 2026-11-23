#!/usr/bin/env python
"""Derive a fresh-identity Workspace copy from an existing Workspace."""

import json
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
    _replace_string_prefix,
    command_retry_matches,
    workspace_command_fingerprint,
    write_workspace_command,
)
from chipcompiler.utility.path import path_is_within

_RUNTIME_COMMANDS_FILENAME = "runtime-commands.json"
_WORKSPACE_COMMANDS_FILENAME = "workspace-commands.json"


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
    retained_candidate_sha256: str = "",
    parent_workspace_directory: Path | None = None,
    original_evidence: frozenset[Path] = frozenset(),
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

    A verified candidate with a retention digest keeps its completed flow.
    Its command receipt binds the copied evidence to the registered parent
    so Project reconciliation can finish an interrupted publication.

    Returns the loaded derived workspace.
    """
    from chipcompiler.data import load_workspace
    from chipcompiler.utility.workspace_lock import workspace_lock

    source = Path(source_directory).expanduser().resolve()
    target = Path(target_directory).expanduser().resolve()
    command_spec = {
        "directory": str(parent_workspace_directory or source),
        "targetDirectory": str(target),
        "resetFromStep": reset_from_step,
        **({"throughStep": through_step} if through_step else {}),
    }
    if retained_candidate_sha256:
        command_spec.update(
            retainedCandidateSha256=retained_candidate_sha256,
            candidateDirectory=str(source),
        )
    fingerprint = workspace_command_fingerprint("derive", command_spec, None)
    if path_is_within(target, source):
        raise WorkspaceLifecycleError(
            "workspace_invalid", f"Target directory is inside the source Workspace: {target}"
        )
    if not retained_candidate_sha256 and not (source / "home" / SNAPSHOT_FILENAME).is_file():
        raise WorkspaceLifecycleError(
            "workspace_invalid", f"Workspace has no Engineering Snapshot: {source}"
        )

    # Blocking acquisition uses a stable path order so two derives can never
    # deadlock. A non-blocking acquisition never waits, so it cannot deadlock
    # either; it takes the source lock first so a busy source fails before the
    # target's sibling lock file is created (#400).
    source_lock = (
        parent_workspace_directory / ".agent" / "operations" / source.name
        if retained_candidate_sha256 and parent_workspace_directory is not None
        else source
    )
    locks = sorted((source_lock, target), key=str) if blocking else (source_lock, target)
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

            def ignore_source_agent(path: str, _names: list[str]) -> list[str]:
                return [".agent"] if Path(path) == source else []

            shutil.copytree(source, staging, ignore=ignore_source_agent)
            home = staging / "home"
            for name in (
                STALE_SNAPSHOT_FILENAME,
                _RUNTIME_COMMANDS_FILENAME,
                _WORKSPACE_COMMANDS_FILENAME,
            ):
                (home / name).unlink(missing_ok=True)

            if retained_candidate_sha256:

                def relocate(value: str) -> str:
                    return _relocate_candidate_path(
                        value, source, parent_workspace_directory, staging
                    )

                _rewrite_staged_paths(staging, relocate, original_evidence)
                _rebase_candidate_params(staging, relocate)
            workspace = load_workspace(staging)
            if workspace is None:
                raise WorkspaceLifecycleError(
                    "workspace_invalid", f"Workspace cannot be opened: {source}"
                )

            if retained_candidate_sha256:
                for result in (staging / "log").glob("*.run.json"):
                    result.unlink()
            else:
                _prepare_derived_flow(workspace, reset_from_step, through_step)

            snapshot = create_engineering_snapshot(
                workspace, workspace_id=target_workspace_id or None, cause=cause
            )

            def publish_path(value: str) -> str:
                if retained_candidate_sha256:
                    return _relocate_candidate_path(value, staging, None, target)
                return _replace_string_prefix(
                    _replace_string_prefix(value, str(source), str(target)),
                    str(staging),
                    str(target),
                )

            _rewrite_staged_paths(staging, publish_path, original_evidence)
            if retained_candidate_sha256:
                _rebase_candidate_params(staging, publish_path)
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


def _relocate_candidate_path(
    value: str, candidate: Path, parent: Path | None, staging: Path
) -> str:
    if not value.startswith("/"):
        return value
    path = Path(value)
    if path.is_relative_to(candidate):
        return str(staging / path.relative_to(candidate))
    # An inherited request can name a previous candidate as its workspace.
    if parent is not None and path.is_relative_to(candidate.parent):
        parts = path.relative_to(candidate.parent).parts
        if parts:
            return str(staging.joinpath(*parts[1:]))
    if parent is not None and path.is_relative_to(parent):
        return str(staging / path.relative_to(parent))
    return value


def _rebase_candidate_params(staging: Path, relocate: Callable[[str], str]) -> None:
    import tomllib

    import tomli_w

    from chipcompiler.utility.file import write_text_atomic

    path = staging / "home" / "params.toml"
    params = tomllib.loads(path.read_text(encoding="utf-8"))
    rewritten = _rewrite_paths(params, relocate)
    if params != rewritten:
        write_text_atomic(path, tomli_w.dumps(rewritten))


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


def _rewrite_paths(value: Any, relocate: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return relocate(value)
    if isinstance(value, list):
        return [_rewrite_paths(item, relocate) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite_paths(item, relocate) for key, item in value.items()}
    return value


def _rewrite_staged_paths(
    staging: Path, relocate: Callable[[str], str], original_evidence: frozenset[Path]
) -> None:
    from chipcompiler.utility import json_write

    for path in staging.rglob("*.json"):
        relative = path.relative_to(staging)
        if relative in original_evidence or any(
            parent in original_evidence for parent in relative.parents
        ):
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rewritten = _rewrite_paths(value, relocate)
        if rewritten != value and not json_write(path, rewritten):
            raise OSError(f"Failed to rewrite staged Workspace path: {path}")
