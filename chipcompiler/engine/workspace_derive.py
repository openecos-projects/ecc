#!/usr/bin/env python
"""Derive a fresh-identity Workspace copy from an existing Workspace."""

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from chipcompiler.engine.snapshot import (
    SNAPSHOT_FILENAME,
    STALE_SNAPSHOT_FILENAME,
    create_engineering_snapshot,
)
from chipcompiler.engine.workspace_lifecycle import (
    WorkspaceLifecycleError,
    _replace_string_prefix,
    _workspace_command_fingerprint,
    _write_workspace_command,
)
from chipcompiler.utility.path import path_is_within

_RUNTIME_COMMANDS_FILENAME = "runtime-commands.json"
_WORKSPACE_COMMANDS_FILENAME = "workspace-commands.json"


def derive_workspace(
    source_directory: str | Path,
    target_directory: str | Path,
    *,
    reset_from_step: str = "",
    command_id: str = "",
    cause: str = "workspace.derived",
) -> Any:
    """Copy ``source_directory`` to ``target_directory`` under a new identity.

    The source stays read-only and byte-identical. The target receives a new
    Engineering Snapshot (fresh workspaceId, revision 1, ``cause``), an empty
    runtime command ledger, and no inherited workspace command records. With an
    empty ``reset_from_step`` the whole flow is prepared for a rerun; otherwise
    only the named step and its flow suffix are reset while earlier steps keep
    their Success state and artifacts.

    Returns the loaded derived workspace.
    """
    from chipcompiler.data import load_workspace
    from chipcompiler.engine.reconcile import _workspace_lock

    source = Path(source_directory).expanduser().resolve()
    target = Path(target_directory).expanduser().resolve()
    if target.exists():
        raise WorkspaceLifecycleError("workspace_exists", f"Workspace already exists: {target}")
    if path_is_within(target, source):
        raise WorkspaceLifecycleError(
            "workspace_invalid", f"Target directory is inside the source Workspace: {target}"
        )
    if not (source / "home" / SNAPSHOT_FILENAME).is_file():
        raise WorkspaceLifecycleError(
            "workspace_invalid", f"Workspace has no Engineering Snapshot: {source}"
        )

    with _workspace_lock(source), _workspace_lock(target):
        if target.exists():
            raise WorkspaceLifecycleError("workspace_exists", f"Workspace already exists: {target}")
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
        staging.rmdir()
        try:
            shutil.copytree(source, staging)
            home = staging / "home"
            for name in (
                STALE_SNAPSHOT_FILENAME,
                _RUNTIME_COMMANDS_FILENAME,
                _WORKSPACE_COMMANDS_FILENAME,
            ):
                (home / name).unlink(missing_ok=True)

            workspace = load_workspace(staging)
            if workspace is None:
                raise WorkspaceLifecycleError(
                    "workspace_invalid", f"Workspace cannot be opened: {source}"
                )

            from chipcompiler.runtime.workspace_api import (
                WorkspaceRuntimeApi,
                build_flow_for_workspace,
            )

            engine_flow = build_flow_for_workspace(workspace)
            if reset_from_step:
                reset_steps = _reset_step_suffix(engine_flow, reset_from_step)
                WorkspaceRuntimeApi._prepare_steps_for_rerun(workspace, engine_flow, reset_steps)
                home_data = getattr(getattr(workspace, "home", None), "data", None)
                if isinstance(home_data, dict):
                    home_data["checklist"] = str(home / "checklist.json")
                _prune_derived_home(workspace, reset_steps)
                _prune_derived_checklist(workspace, reset_steps)
            else:
                import chipcompiler.data as data_api

                data_api.prepare_workspace_for_rerun(
                    workspace, engine_flow, preserve_user_inputs=True
                )

            _rewrite_staged_paths(
                staging,
                ((str(source), str(target)), (str(staging), str(target))),
            )
            snapshot = create_engineering_snapshot(workspace, cause=cause)
            if command_id:
                _write_workspace_command(
                    staging,
                    command_id,
                    _workspace_command_fingerprint(
                        "derive",
                        {
                            "directory": str(source),
                            "targetDirectory": str(target),
                            "resetFromStep": reset_from_step,
                        },
                        None,
                    ),
                    snapshot["workspaceId"],
                    snapshot["workspaceRevision"],
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


def _reset_step_suffix(engine_flow, reset_from_step: str) -> list:
    workspace_steps = list(getattr(engine_flow, "workspace_steps", []))
    index = next(
        (
            position
            for position, step in enumerate(workspace_steps)
            if str(getattr(step, "name", "")).casefold() == reset_from_step.casefold()
        ),
        -1,
    )
    if index < 0:
        raise WorkspaceLifecycleError(
            "flow_step_not_found", f"Flow Step not found: {reset_from_step}"
        )
    return workspace_steps[index:]


def _prune_derived_home(workspace, reset_steps) -> None:
    home = getattr(workspace, "home", None)
    data = getattr(home, "data", None)
    if home is None or not isinstance(data, dict):
        return
    wiped = {Path(str(getattr(step, "directory", ""))).name for step in reset_steps}
    wiped.discard("")
    if isinstance(data.get("layout"), str) and _path_in_reset_scope(data["layout"], wiped):
        data["layout"] = ""
    metrics = data.get("metrics")
    if isinstance(metrics, dict):
        data["metrics"] = {
            key: value
            for key, value in metrics.items()
            if not (isinstance(value, str) and _path_in_reset_scope(value, wiped))
        }
    save = getattr(home, "save", None)
    if callable(save):
        save()


def _path_in_reset_scope(value: str, wiped: set[str]) -> bool:
    segments = value.strip().replace("\\", "/").split("/")
    return any(segment in wiped for segment in segments if segment)


def _prune_derived_checklist(workspace, reset_steps) -> None:
    from chipcompiler.data import Checklist

    home = getattr(workspace, "home", None)
    data = getattr(home, "data", None)
    checklist_text = data.get("checklist", "") if isinstance(data, dict) else ""
    path = (
        Path(checklist_text)
        if checklist_text
        else Path(str(getattr(workspace, "directory", ""))) / "home" / "checklist.json"
    )
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


def _rewrite_staged_paths(staging: Path, replacements: tuple[tuple[str, str], ...]) -> None:
    from chipcompiler.utility import json_write

    for path in staging.rglob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rewritten = value
        for source, target in replacements:
            rewritten = _replace_string_prefix(rewritten, source, target)
        if rewritten != value and not json_write(path, rewritten):
            raise OSError(f"Failed to rewrite staged Workspace path: {path}")
