"""Inspect, cancel, and reconcile manifest-managed ECC run processes."""

from __future__ import annotations

from pathlib import Path

from chipcompiler.engine.interrupted_run import recover_interrupted_run
from chipcompiler.engine.reconcile import _workspace_lock
from chipcompiler.project.manifest import load_manifest
from chipcompiler.project.manifest_write import manifest_lock, update_manifest_locked
from chipcompiler.project.runtime_processes import (
    RuntimeProcessError,
    identity_is_live,
    read_runtime_process,
    signal_runtime_process,
    validate_runtime_entry,
)


def inspect_process(project_dir: str | Path, workspace_id: str, run_id: str | None) -> dict:
    project = Path(project_dir).resolve()
    entry = read_runtime_process(project, workspace_id, run_id)
    workspace = _workspace_path(project, workspace_id)
    local = _entry_is_local(entry)
    live = identity_is_live(entry) if local else False
    try:
        with _workspace_lock(workspace, blocking=False):
            lock_busy = False
    except BlockingIOError:
        lock_busy = True
    if local and live and lock_busy:
        return entry
    if not local and lock_busy:
        raise RuntimeProcessError("workspace_busy", "Remote Workspace lock is held")
    raise RuntimeProcessError("process_not_found", "Runtime process identity is stale")


def cancel_process(
    project_dir: str | Path, workspace_id: str, run_id: str, *, force: bool
) -> dict:
    entry = read_runtime_process(project_dir, workspace_id, run_id)
    signal_runtime_process(entry, force=force)
    return entry


def reconcile_process(
    project_dir: str | Path,
    workspace_id: str,
    run_id: str | None,
    *,
    blocking: bool,
) -> tuple[str, ...]:
    project = Path(project_dir).resolve()
    workspace = _workspace_path(project, workspace_id)
    with (
        _workspace_lock(workspace, blocking=blocking),
        manifest_lock(project, blocking=blocking),
    ):
        manifest = load_manifest(str(project))
        processes = manifest.raw.get("runtime_processes", {})
        if not isinstance(processes, dict):
            raise RuntimeProcessError(
                "invalid_runtime_processes", "runtime process registry is invalid"
            )
        raw_entry = processes.get(workspace_id)
        if raw_entry is None:
            if run_id is not None:
                raise RuntimeProcessError(
                    "process_not_found", "The requested runtime process is not registered"
                )
            recovered = recover_interrupted_run(workspace, run_id=None, allow_markerless=True)
            return recovered
        entry = validate_runtime_entry(raw_entry)
        if run_id is None or entry["run_id"] != run_id:
            raise RuntimeProcessError("process_not_found", "Registered run ID does not match")
        if _entry_is_local(entry) and identity_is_live(entry):
            raise RuntimeProcessError("workspace_busy", "Runtime process is still alive")
        recovered = recover_interrupted_run(
            workspace, run_id=run_id, allow_markerless=False
        )

        def mutate(document: dict) -> None:
            current = document.get("runtime_processes", {})
            value = current.get(workspace_id) if isinstance(current, dict) else None
            if not isinstance(value, dict) or value.get("run_id") != run_id:
                raise RuntimeProcessError(
                    "process_identity_changed", "Runtime registry changed during reconcile"
                )
            del current[workspace_id]

        if not update_manifest_locked(project, mutate):
            raise RuntimeProcessError(
                "runtime_reconcile_failed", "Project Manifest update failed"
            )
        return recovered


def _workspace_path(project: Path, workspace_id: str) -> Path:
    manifest = load_manifest(str(project))
    workspace = manifest.find_workspace(workspace_id)
    if workspace is None:
        raise RuntimeProcessError("workspace_not_declared", "Workspace is not registered")
    return Path(workspace.workspace_path).resolve()


def _entry_is_local(entry: dict) -> bool:
    from chipcompiler.project.runtime_processes import _boot_id, _host_id

    return entry["host_id"] == _host_id() and entry["boot_id"] == _boot_id()
