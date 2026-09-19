"""Spec-mode drift disclosure for CLI runs of GUI-created workspaces.

A GUI (spec-mode) workspace records its parameter intent in
``home/engineering-snapshot.json`` (``workspaceSpec``); the CLI's explicit
``--workspace`` run path only reads ``home/params.toml``. When a user edits
``params.toml`` by hand (or via ``ecc param set --workspace``), the snapshot
stays behind — its ``workspaceRevision`` does not move — and the GUI-side
optimistic concurrency silently operates on a stale spec. This module
detects that drift for the CLI run paths and builds the warning record.
"""

import os
from pathlib import Path


def workspace_spec_drift_warning(run_dir: str) -> dict | None:
    """Warning record when ``home/params.toml`` is newer than the snapshot.

    None when the workspace carries no Engineering Snapshot (a CLI-born
    workspace has nothing to drift against) or when the snapshot is at least
    as new as the parameter file. Only a warning: execution semantics are
    unchanged.
    """
    from chipcompiler.cli.core.records import warning_record

    home = Path(run_dir) / "home"
    snapshot_path = home / "engineering-snapshot.json"
    params_path = home / "params.toml"
    if not snapshot_path.is_file() or not params_path.is_file():
        return None
    try:
        params_mtime = params_path.stat().st_mtime
        snapshot_mtime = snapshot_path.stat().st_mtime
    except OSError:
        return None
    if params_mtime <= snapshot_mtime:
        return None
    return warning_record(
        "workspace_spec_drift",
        workspace=os.path.abspath(run_dir),
        reason="home/params.toml is newer than home/engineering-snapshot.json: "
        "this spec-mode workspace was modified outside the GUI snapshot "
        "(workspaceRevision is unchanged), so the GUI snapshot may be stale; "
        "open the workspace in the GUI or apply changes via "
        "'ecc param set --workspace' so the snapshot follows",
    )
