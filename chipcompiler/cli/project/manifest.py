#!/usr/bin/env python

"""``project.json`` manifest support for the CLI.

The manifest is the GUI's project descriptor (schema v1). The CLI reads it
for configuration layering and run discovery, generates it for virgin
projects, and writes back run status. All writes go through one
read-modify-write helper so status write-back and migration entry-append
share the same atomicity story.

This module sits on the CLI startup path (imported by
cli/core/invocation.py): keep module-level imports cheap — no
chipcompiler.data imports here.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "project.json"

# GUI display names for the canonical chain; presets are named prefixes.
MANIFEST_FLOW_STEPS = (
    "Synth",
    "Floor",
    "Fanout",
    "Place",
    "CTS",
    "Legal",
    "Route",
    "DRC",
    "LVS",
    "Filler",
    "RCX",
    "STA",
    "Harden",
)

PRESET_MANIFEST_RANGE = {
    "syn_sta": ("Synth", "Synth"),
    "rtl2gds": ("Synth", "Filler"),
    "rcx": ("Synth", "STA"),
    "harden": ("Synth", "Harden"),
}

_WORKSPACE_STATUSES = frozenset(
    {"success", "failed", "running", "in_progress", "not_started", "archived"}
)

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


class ManifestError(ValueError):
    """Raised when a project.json manifest cannot be used (manifest_invalid)."""


@dataclass(frozen=True)
class ManifestWorkspace:
    workspace_id: str
    workspace_path: str
    start_step: str
    end_step: str
    status: str
    parameter_patch: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectManifest:
    project_dir: str
    path: str
    project_id: str
    name: str
    design_name: str
    base_design: dict
    objectives: dict
    workspaces: tuple[ManifestWorkspace, ...]
    qor_baseline: dict | None
    raw: dict

    def active_workspaces(self) -> list[ManifestWorkspace]:
        return [w for w in self.workspaces if w.status != "archived"]

    def find_workspace(self, run_id: str) -> ManifestWorkspace | None:
        """Match a run id against workspace_id, or a declared path tail."""
        for workspace in self.workspaces:
            if workspace.workspace_id == run_id:
                return workspace
        for workspace in self.workspaces:
            tail = os.path.basename(workspace.workspace_path.rstrip("/"))
            if tail == run_id:
                return workspace
        return None


def _optional_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _record(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _normalize_workspace_entry(value: Any, index: int, project_dir: str) -> ManifestWorkspace:
    source = _record(value)
    workspace_id = _optional_str(source.get("workspace_id"))
    workspace_path = _optional_str(source.get("workspace_path"))
    if not workspace_id or not workspace_path:
        raise ManifestError(f"workspaces[{index}] requires workspace_id and workspace_path")
    resolved = Path(workspace_path)
    if not resolved.is_absolute():
        resolved = Path(project_dir) / resolved
    try:
        resolved.resolve().relative_to(Path(project_dir).resolve())
    except ValueError:
        raise ManifestError(
            f"workspaces[{index}] workspace_path escapes the project root: {workspace_path}"
        ) from None
    status = source.get("status")
    if status not in _WORKSPACE_STATUSES:
        status = "not_started"
    return ManifestWorkspace(
        workspace_id=workspace_id,
        workspace_path=str(resolved),
        start_step=_optional_str(source.get("start_step")) or "Synth",
        end_step=_optional_str(source.get("end_step")) or "Harden",
        status=status,
        parameter_patch=_record(source.get("parameter_patch")),
        raw=dict(source),
    )


def _validate_mpc(value: Any) -> None:
    """Mirror the GUI parser's mpc rules: null or a well-formed MPC record."""
    if value is None:
        return
    source = _record(value)
    if not source:
        raise ManifestError("invalid project manifest: mpc must be an object or null")
    resource_id = _optional_str(source.get("resource_id"))
    if not resource_id.startswith("mpc:") or len(resource_id) == 4:
        raise ManifestError("invalid project manifest: mpc.resource_id must be an MPC id")
    for field_name in ("display_name", "installed_version", "path", "spec_path"):
        if not _optional_str(source.get(field_name)):
            raise ManifestError(f"invalid project manifest: mpc.{field_name} is required")
    mpc_path = source["path"].rstrip("/")
    if source["spec_path"] != f"{mpc_path}/spec/spec.json.in":
        raise ManifestError(
            "invalid project manifest: mpc.spec_path must reference spec/spec.json.in"
        )
    design = _record(source.get("design"))
    if (
        not design
        or not isinstance(design.get("index"), int)
        or design["index"] < 0
        or not _optional_str(design.get("design_name"))
    ):
        raise ManifestError(
            "invalid project manifest: mpc.design requires a non-negative index and design_name"
        )
    if not isinstance(source.get("core_template"), dict):
        raise ManifestError("invalid project manifest: mpc.core_template must be an object")


def load_manifest(project_dir: str) -> ProjectManifest:
    """Load and tolerantly normalize ``<project_dir>/project.json``.

    Mirrors the GUI parser's contract: schema_version 1 and a workspaces
    array are required, everything else is default-filled. Raises
    ManifestError on parse failure, root_path mismatch, or a workspace
    path outside the project root.
    """
    path = os.path.join(project_dir, MANIFEST_FILENAME)
    try:
        with open(path, encoding="utf-8") as f:
            source = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"invalid project manifest: {path}: {exc}") from exc

    if not isinstance(source, dict):
        raise ManifestError("invalid project manifest: top level must be an object")
    if source.get("schema_version") != 1:
        raise ManifestError("invalid project manifest: schema_version 1 is required")
    raw_workspaces = source.get("workspaces")
    if not isinstance(raw_workspaces, list):
        raise ManifestError("invalid project manifest: workspaces must be an array")

    root_path = _optional_str(source.get("root_path"))
    if not root_path:
        raise ManifestError("invalid project manifest: root_path is required")
    if os.path.realpath(root_path) != os.path.realpath(project_dir):
        raise ManifestError(
            f"invalid project manifest: root_path {root_path} does not match {project_dir}"
        )
    design_name = _optional_str(source.get("design_name"))
    if not design_name:
        raise ManifestError("invalid project manifest: design_name is required")

    name = _optional_str(source.get("name")) or os.path.basename(project_dir) or "project"
    base_design = _record(source.get("base_design"))
    base_design = {**base_design, "parameters": _record(base_design.get("parameters"))}
    objectives = _record(source.get("objectives"))
    objectives = {
        **DEFAULT_OBJECTIVES,
        **objectives,
        "directions": {
            **DEFAULT_OBJECTIVES["directions"],
            **_record(objectives.get("directions")),
        },
    }
    qor_baseline_raw = _record(source.get("qor_baseline"))
    qor_baseline = None
    if _optional_str(qor_baseline_raw.get("workspace_id")):
        qor_baseline = {
            "workspace_id": qor_baseline_raw["workspace_id"],
            "reason": _optional_str(qor_baseline_raw.get("reason")) or "Project QoR baseline",
        }

    _validate_mpc(source.get("mpc"))

    return ProjectManifest(
        project_dir=project_dir,
        path=path,
        project_id=_optional_str(source.get("project_id")) or f"proj_{_slugify(name)}",
        name=name,
        design_name=design_name,
        base_design=base_design,
        objectives=objectives,
        workspaces=tuple(
            _normalize_workspace_entry(entry, index, project_dir)
            for index, entry in enumerate(raw_workspaces)
        ),
        qor_baseline=qor_baseline,
        raw=source,
    )


def find_manifest(project_dir: str) -> str | None:
    path = os.path.join(project_dir, MANIFEST_FILENAME)
    return path if os.path.isfile(path) else None


def has_legacy_runs_layout(project_dir: str) -> bool:
    runs_dir = os.path.join(project_dir, "runs")
    if not os.path.isdir(runs_dir):
        return False
    try:
        return any(os.path.isdir(os.path.join(runs_dir, entry)) for entry in os.listdir(runs_dir))
    except OSError:
        return False


def classify_project(project_dir: str) -> str:
    """Classify a project directory: manifest | legacy | virgin."""
    if find_manifest(project_dir) is not None:
        return "manifest"
    if has_legacy_runs_layout(project_dir):
        return "legacy"
    return "virgin"


def assemble_config(manifest: ProjectManifest, workspace: ManifestWorkspace | None) -> dict:
    """Flatten the manifest into a parameter payload (lowest precedence layer).

    ``base_design.parameters`` plus the workspace's ``parameter_patch`` form
    the base layer beneath project ecc.toml and --set overrides.
    """
    parameters = dict(manifest.base_design.get("parameters") or {})
    if workspace is not None:
        for key, change in workspace.parameter_patch.items():
            if isinstance(change, dict) and "to" in change:
                parameters[key] = change["to"]
            else:
                parameters[key] = change
    if manifest.design_name and not _optional_str(parameters.get("design")):
        parameters["design"] = manifest.design_name
    return {
        "pdk": _optional_str(manifest.base_design.get("pdk")),
        "pdk_root": _optional_str(manifest.base_design.get("pdk_root")),
        "design_name": manifest.design_name,
        "top_module": _optional_str(manifest.base_design.get("top_module")),
        "clock": _optional_str(manifest.base_design.get("clock")),
        "rtl_list": [
            item for item in manifest.base_design.get("rtl_list") or [] if isinstance(item, str)
        ],
        "origin_verilog": _optional_str(manifest.base_design.get("origin_verilog")),
        "parameters": parameters,
    }


def _slugify(value: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "project"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


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
    parameters = _record(base_design.get("parameters"))
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
            **{k: v for k, v in base_design.items() if k != "parameters" and v},
            "parameters": parameters,
            "rtl_list": [
                item for item in base_design.get("rtl_list") or [] if isinstance(item, str)
            ],
        },
        "objectives": json.loads(json.dumps(DEFAULT_OBJECTIVES)),
        "workspaces": [
            {
                "workspace_id": workspace_id,
                "name": design_name,
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
        ],
        "mpc": None,
        "best_workspace": None,
        "qor_baseline": {"workspace_id": workspace_id, "reason": "Default project QoR baseline"},
    }
    return document


def write_manifest_if_absent(project_dir: str, document: dict) -> bool:
    """Write the manifest only when it does not exist (virgin generation race).

    Returns True when written; False when a manifest appeared concurrently —
    the caller discards its document, reloads, and continues read-only.
    """
    path = os.path.join(project_dir, MANIFEST_FILENAME)
    content = json.dumps(document, indent=2) + "\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    except OSError as exc:
        logger.warning("manifest write failed: %s: %s", path, exc)
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as exc:
        logger.warning("manifest write failed: %s: %s", path, exc)
        os.unlink(path)
        return False
    return True


def update_manifest(project_dir: str, mutator) -> bool:
    """Read-modify-write the manifest atomically (re-read + patch + replace).

    The mutator receives the parsed document and edits it in place. Returns
    False (with a warning) when the manifest is missing, unreadable, or the
    write fails — callers degrade to a warning, never a run failure.
    """
    path = os.path.join(project_dir, MANIFEST_FILENAME)
    try:
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("manifest update skipped (unreadable): %s: %s", path, exc)
        return False
    if not isinstance(document, dict):
        logger.warning("manifest update skipped (not an object): %s", path)
        return False

    mutator(document)
    document["updated_at"] = _now_iso()

    import tempfile

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
