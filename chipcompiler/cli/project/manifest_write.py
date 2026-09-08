#!/usr/bin/env python

"""Manifest write, mutation, and registration operations for the CLI.

All ``project.json`` writes go through one read-modify-write helper so
status write-back and migration entry-append share the same atomicity
story. Loading and normalization live in
chipcompiler.cli.project.manifest; this module imports from it, never
the reverse.

Like manifest.py, this module sits on the CLI startup path (imported by
run dispatch and migration flows): keep module-level imports cheap — no
chipcompiler.data imports here.
"""

import json
import logging
import os
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chipcompiler.cli.project.manifest import (
    _CANONICAL_TO_MANIFEST_STEP,
    MANIFEST_FILENAME,
    PRESET_MANIFEST_RANGE,
    ManifestError,
    _record,
    _slugify,
    base_design_from_config,
)

logger = logging.getLogger(__name__)

DEFAULT_OBJECTIVES = {
    "primary": "timing",
    "directions": {
        "wns": "maximize",
        "tns": "maximize",
        "area": "minimize",
        "drc_count": "minimize",
        "lvs_count": "minimize",
        "power": "minimize",
    },
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def manifest_workspace_entry(
    workspace_id: str,
    *,
    name: str,
    workspace_path: str,
    start_step: str,
    end_step: str,
    status: str,
    now: str,
) -> dict:
    """One complete schema-v1 workspaces[] entry, every field materialized.

    The single builder for generated manifests and migration previews, so
    the previewed entry and the applied entry are the same object shape.
    """
    return {
        "workspace_id": workspace_id,
        "name": name,
        "workspace_path": workspace_path,
        "source_workspace_id": None,
        "branch_from": None,
        "start_step": start_step,
        "end_step": end_step,
        "status": status,
        "created_at": now,
        "updated_at": now,
        "parameter_patch": {},
        "metrics_summary": {},
        "step_metrics": {},
    }


def build_manifest_document(
    project_dir: str,
    *,
    design_name: str,
    base_design: dict,
    workspace_id: str,
    workspace_path: str,
    start_step: str,
    end_step: str,
    status: str = "running",
) -> dict:
    """Assemble a schema-v1 manifest for a virgin project's first run."""
    now = _now_iso()
    name = os.path.basename(os.path.normpath(project_dir)) or "project"
    document: dict[str, Any] = {
        "schema_version": 1,
        "project_id": f"proj_{_slugify(name)}",
        "name": name,
        "design_name": design_name,
        "description": "",
        "root_path": project_dir,
        "created_at": now,
        "updated_at": now,
        "base_design": {
            **{key: value for key, value in base_design.items() if key != "parameters" and value},
            "parameters": _record(base_design.get("parameters")),
            "rtl_list": [
                item for item in base_design.get("rtl_list") or [] if isinstance(item, str)
            ],
        },
        "objectives": json.loads(json.dumps(DEFAULT_OBJECTIVES)),
        "workspaces": [
            manifest_workspace_entry(
                workspace_id,
                name=design_name,
                workspace_path=workspace_path,
                start_step=start_step,
                end_step=end_step,
                status=status,
                now=now,
            )
        ],
        "mpc": None,
        "best_workspace": None,
        "qor_baseline": {"workspace_id": workspace_id, "reason": "Default project QoR baseline"},
    }
    return document


def write_manifest_if_absent(project_dir: str, document: dict) -> bool:
    """Write the manifest only when it does not exist (virgin generation race).

    Fully written and fsynced at a temp path, then linked into place:
    readers never see a partial file, and a concurrent creator wins the
    link — ours is discarded and the caller continues read-only.
    """
    path = os.path.join(project_dir, MANIFEST_FILENAME)
    content = json.dumps(document, indent=2) + "\n"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            dir=project_dir,
            delete=False,
            prefix=f".{MANIFEST_FILENAME}.",
            suffix=".tmp",
            encoding="utf-8",
        ) as f:
            tmp_path = f.name
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        # Mode stays the tempfile default (0600), matching json_write's
        # convention for newly created state files.
        os.link(tmp_path, path)
        return True
    except FileExistsError:
        return False
    except OSError as exc:
        logger.warning("manifest write failed: %s: %s", path, exc)
        return False
    finally:
        if tmp_path is not None:
            Path(tmp_path).unlink(missing_ok=True)


def _read_manifest_document(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return document if isinstance(document, dict) else None


def update_manifest(project_dir: str, mutator) -> bool:
    """Read-modify-write the manifest atomically (locked re-read + patch + replace).

    The whole read-modify-replace runs under ``.manifest.lock`` (flock):
    two cooperating writers can no longer both complete the fresh read
    before either replaces, so neither loses the other's update. The
    mutator receives the parsed document and edits it in place. When an
    unrelated change lands between the read and the write, the mutator is
    re-applied to the freshest document instead of overwriting the change.
    Project-level fields (including updated_at) are owned by the mutator.
    Returns False (with a warning) when the manifest is missing, unreadable,
    the lock cannot be taken, or the write fails — callers degrade to a
    warning, never a run failure.
    """
    from chipcompiler.cli.project.migrate_fs import flock_file

    path = os.path.join(project_dir, MANIFEST_FILENAME)
    try:
        with flock_file(os.path.join(project_dir, ".manifest.lock"), exclusive=True):
            return _update_manifest_locked(path, mutator)
    except OSError as exc:
        # An untakeable lock (e.g. a directory at the lock path) degrades
        # like any write failure: a warning, never an uncaught exception —
        # the migration registration path relies on False to roll back.
        logger.warning("manifest update failed: %s: %s", path, exc)
        return False


def _update_manifest_locked(path: str, mutator) -> bool:
    base = _read_manifest_document(path)
    if base is None:
        logger.warning("manifest update skipped (unreadable): %s", path)
        return False

    document = deepcopy(base)
    mutator(document)

    fresh = _read_manifest_document(path)
    if fresh is not None and fresh != base:
        # An unrelated edit landed after our read: re-apply the mutator to
        # the freshest document so the interleaved change survives.
        document = fresh
        mutator(document)

    target = Path(path)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            dir=target.parent,
            delete=False,
            prefix=f".{target.name}.",
            suffix=".tmp",
            encoding="utf-8",
        ) as f:
            tmp_path = Path(f.name)
            json.dump(document, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
        return True
    except OSError as exc:
        logger.warning("manifest update failed: %s: %s", path, exc)
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        return False


def write_back_workspace_status(project_dir: str, workspace_id: str, status: str) -> bool:
    """Update one workspace entry's status (and updated_at) after a run."""

    def mutate(document: dict) -> None:
        for entry in document.get("workspaces", []):
            if isinstance(entry, dict) and entry.get("workspace_id") == workspace_id:
                entry["status"] = status
                entry["updated_at"] = _now_iso()

    return update_manifest(project_dir, mutate)


def remove_workspace_registration(project_dir: str, workspace_id: str) -> bool:
    """Roll back a pre-registration: drop the freshly added entry.

    Used when an overwrite run against an undeclared workspace fails before
    the replacement is constructed: the restored previous workspace must not
    be shadowed by a stale ``not_started`` entry this invocation created.
    """

    def mutate(document: dict) -> None:
        workspaces = document.get("workspaces")
        if isinstance(workspaces, list):
            document["workspaces"] = [
                entry
                for entry in workspaces
                if not (isinstance(entry, dict) and entry.get("workspace_id") == workspace_id)
            ]
            document["updated_at"] = _now_iso()

    return update_manifest(project_dir, mutate)


def manifest_range_for_flow(cfg, flow_config: dict | None) -> tuple[str, str]:
    """Return the GUI manifest range for a workspace's effective target."""
    if isinstance(flow_config, dict) and flow_config.get("start_step"):
        from chipcompiler.rtl2gds import normalize_flow_step

        start = normalize_flow_step(flow_config["start_step"])
        end = normalize_flow_step(flow_config.get("end_step") or start)
        try:
            return (_CANONICAL_TO_MANIFEST_STEP[start], _CANONICAL_TO_MANIFEST_STEP[end])
        except KeyError as exc:
            raise ManifestError(f"unknown workspace flow step: {exc.args[0]}") from None
    return PRESET_MANIFEST_RANGE.get(cfg.flow_preset, ("Synth", "Harden"))


def pre_register_workspace(
    project_dir: str,
    *,
    cfg,
    pdk_root: str,
    workspace_id: str,
    workspace_path: str,
    flow_config: dict | None,
) -> str:
    """Atomically register a fresh managed workspace before filesystem creation.

    Returns ``registered``, ``existing``, ``conflict``, or ``failed``. A
    workspace entry intentionally contains no input snapshot: copied files and
    the workspace config are the reproducibility boundary.
    """
    try:
        start_step, end_step = manifest_range_for_flow(cfg, flow_config)
    except ManifestError:
        return "failed"
    now = _now_iso()
    manifest_path = os.path.join(project_dir, MANIFEST_FILENAME)
    if not os.path.lexists(manifest_path):
        document = build_manifest_document(
            project_dir,
            design_name=cfg.design_name,
            base_design=base_design_from_config(cfg, pdk_root),
            workspace_id=workspace_id,
            workspace_path=workspace_path,
            start_step=start_step,
            end_step=end_step,
            status="not_started",
        )
        if write_manifest_if_absent(project_dir, document):
            return "registered"
        # A concurrent creator won the link race: fall through and apply the
        # same registration mutation under the manifest lock instead of
        # aborting this run. A genuine I/O failure fails again below.

    outcome = "registered"

    def mutate(document: dict) -> None:
        nonlocal outcome
        workspaces = document.get("workspaces")
        if not isinstance(workspaces, list):
            outcome = "failed"
            return
        for entry in workspaces:
            if not isinstance(entry, dict) or entry.get("workspace_id") != workspace_id:
                continue
            if os.path.realpath(str(entry.get("workspace_path", ""))) == os.path.realpath(
                workspace_path
            ):
                outcome = "existing"
            else:
                outcome = "conflict"
            return
        workspaces.append(
            manifest_workspace_entry(
                workspace_id,
                name=cfg.design_name,
                workspace_path=workspace_path,
                start_step=start_step,
                end_step=end_step,
                status="not_started",
                now=now,
            )
        )
        document["updated_at"] = now

    if not update_manifest(project_dir, mutate):
        return "failed"
    return outcome
