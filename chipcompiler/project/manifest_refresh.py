#!/usr/bin/env python

"""Manifest derived-field refresh from workspace directory facts.

A workspace entry's ``start_step``/``end_step``/``status``/``parameter_patch``
are DERIVED: the workspace directory is the truth and project.json its
projection. After an in-place workspace update (``ecc workspace refresh``,
RPC ``update_workspace``) or an idempotent re-registration, the owning
entry silently re-converges on the directory — only ``updated_at`` records
the correction. Lineage (``source_workspace_id``/``branch_from``), identity,
and declared policy (``skip_steps``) are never rewritten here.

Like manifest.py/manifest_write.py this module sits on the CLI startup
path: keep module-level imports cheap — chipcompiler.data and the CLI
inspection helpers are imported inside function bodies.
"""

import logging
from copy import deepcopy
from pathlib import Path

from chipcompiler.project.manifest import _CANONICAL_TO_MANIFEST_STEP
from chipcompiler.project.manifest_write import _now_iso, update_manifest

logger = logging.getLogger(__name__)

DERIVED_FIELDS = ("start_step", "end_step", "status", "parameter_patch")

# Identity/config-boundary keys never surface in a parameter_patch diff.
_PATCH_EXCLUDED_KEYS = frozenset(
    {
        "_flow",
        "pdk",
        "pdk_root",
        "pdk_config",
        "design",
        "top_module",
        "clock",
        "config_overrides",
        "workspace_param_overrides",
    }
)


def flow_range_from_ledger(flow_data: object) -> tuple[str, str] | None:
    """(start, end) manifest step names from a parsed flow.json ledger."""
    if not isinstance(flow_data, dict):
        return None
    names = [
        step.get("name")
        for step in flow_data.get("steps", [])
        if isinstance(step, dict) and isinstance(step.get("name"), str)
    ]
    if not names:
        return None
    return (
        _CANONICAL_TO_MANIFEST_STEP.get(names[0], names[0]),
        _CANONICAL_TO_MANIFEST_STEP.get(names[-1], names[-1]),
    )


def manifest_status_of(flow_data: object) -> str:
    """Manifest status for a parsed flow.json ledger.

    Terminal run results surface verbatim; anything else — a fresh or
    partially executed ledger, a missing or corrupt file — is a workspace
    without a completed run: ``not_started``.
    """
    if isinstance(flow_data, dict):
        from chipcompiler.cli.inspection.discovery import get_run_status

        observed = get_run_status(flow_data)
        if observed in ("success", "failed"):
            return observed
    return "not_started"


def parameter_patch_of(parameters: dict, base_parameters: dict | None) -> dict:
    """The workspace's parameter diff against the project base layer."""
    base = base_parameters or {}
    return {
        key: {"from": deepcopy(base.get(key)), "to": deepcopy(value)}
        for key, value in parameters.items()
        if key not in _PATCH_EXCLUDED_KEYS and base.get(key) != value
    }


def manifest_base_parameters(document: dict) -> dict:
    """The manifest document's base_design.parameters (the patch diff base)."""
    base_design = document.get("base_design")
    parameters = base_design.get("parameters") if isinstance(base_design, dict) else None
    return parameters if isinstance(parameters, dict) else {}


def derive_workspace_fields(workspace_dir: str | Path, base_parameters: dict | None) -> dict:
    """Directory-derived manifest fields for one workspace.

    Unreadable sources degrade instead of failing: a missing ledger derives
    the default range and ``not_started``; unreadable params omit
    ``parameter_patch`` so the stored patch is left alone.
    """
    from chipcompiler.cli.inspection.discovery import read_flow_json

    flow_data = read_flow_json(str(workspace_dir))
    start_step, end_step = flow_range_from_ledger(flow_data) or ("Synth", "Harden")
    derived = {
        "start_step": start_step,
        "end_step": end_step,
        "status": manifest_status_of(flow_data),
    }
    try:
        from chipcompiler.data.workspace_config import load_workspace_config

        parameters = load_workspace_config(workspace_dir)
    except Exception as exc:
        logger.warning(
            "workspace parameters unreadable; parameter_patch not re-derived: %s: %s",
            workspace_dir,
            exc,
        )
    else:
        derived["parameter_patch"] = parameter_patch_of(parameters, base_parameters)
    return derived


def apply_derived_fields(entry: dict, derived: dict) -> bool:
    """Patch a manifest entry's derived fields in place; True when changed.

    Archived entries are frozen: archive/restore is owned by the archive
    mutation, not by directory facts.
    """
    if entry.get("status") == "archived":
        return False
    changed = False
    for key in DERIVED_FIELDS:
        if key in derived and entry.get(key) != derived[key]:
            entry[key] = deepcopy(derived[key])
            changed = True
    return changed


def refresh_workspace_derived_fields(project_dir: str, workspace_id: str) -> bool:
    """Re-derive one entry's derived fields from its workspace directory.

    The whole read-derive-write runs under the project manifest lock.
    Returns False only when the manifest write itself fails (see
    ``update_manifest``); a missing entry degrades to a no-op.
    """

    def mutate(document: dict) -> None:
        for entry in document.get("workspaces", []):
            if not isinstance(entry, dict) or entry.get("workspace_id") != workspace_id:
                continue
            declared = entry.get("workspace_path")
            if not isinstance(declared, str) or not declared.strip():
                return
            workspace_dir = Path(declared).expanduser()
            if not workspace_dir.is_absolute():
                workspace_dir = Path(project_dir) / workspace_dir
            derived = derive_workspace_fields(workspace_dir, manifest_base_parameters(document))
            if apply_derived_fields(entry, derived):
                timestamp = _now_iso()
                entry["updated_at"] = timestamp
                document["updated_at"] = timestamp
            return

    return update_manifest(project_dir, mutate)
