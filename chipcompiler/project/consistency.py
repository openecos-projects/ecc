"""project.json ↔ workspace-directory consistency checks and explicit repair.

``ecc project doctor`` compares the manifest against workspace directory
facts and reports three inconsistency classes:

- ``derived-field-mismatch``: an entry's derived fields (``start_step``,
  ``end_step``, ``status``, ``parameter_patch``) disagree with the
  workspace directory. The directory is the truth.
- ``missing-directory``: an entry's ``workspace_path`` does not exist.
- ``unregistered-directory``: a workspace directory exists directly under
  the project root without a manifest entry.

Checks are read-only. Repair (``--fix``) rebuilds derived fields from
directory facts, removes dead entries (mirroring the delete-workspace
reference cleanup), and registers unregistered directories through the
existing inspection + registration path. Archived entries keep their
lifecycle status — only their directory existence is checked.

Like the other manifest modules, this one may sit on the CLI startup
path: keep module-level imports cheap — no chipcompiler.data imports.
"""

import os
from dataclasses import dataclass

from chipcompiler.project.manifest import ManifestError, ProjectManifest
from chipcompiler.project.manifest_refresh import apply_derived_fields
from chipcompiler.project.manifest_write import _now_iso, update_manifest

DERIVED_FIELD_MISMATCH = "derived-field-mismatch"
MISSING_DIRECTORY = "missing-directory"
UNREGISTERED_DIRECTORY = "unregistered-directory"


@dataclass(frozen=True)
class DerivedFields:
    """The manifest entry fields a workspace directory implies."""

    start_step: str
    end_step: str
    status: str
    parameter_patch: dict


@dataclass(frozen=True)
class ConsistencyFinding:
    check: str
    workspace_id: str
    workspace_path: str
    detail: str
    # Directory-derived truth for repair; None when the directory exists
    # but its workspace facts cannot be read at all.
    derived: DerivedFields | None = None


@dataclass(frozen=True)
class FixAction:
    finding: ConsistencyFinding
    action: str  # rebuilt | removed | registered | existing | unchanged | failed
    detail: str = ""


def find_inconsistencies(manifest: ProjectManifest) -> list[ConsistencyFinding]:
    """All manifest ↔ directory inconsistencies, in a stable order.

    Entry checks follow manifest order; unregistered directories follow
    sorted directory names.
    """
    findings = []
    for entry in manifest.workspaces:
        finding = _check_entry(manifest, entry)
        if finding is not None:
            findings.append(finding)
    findings.extend(_scan_unregistered(manifest))
    return findings


def repair_findings(
    manifest: ProjectManifest, findings: list[ConsistencyFinding]
) -> list[FixAction]:
    """Repair every finding explicitly, one audited action per finding."""
    actions = []
    for finding in findings:
        if finding.check == UNREGISTERED_DIRECTORY:
            actions.append(_register_directory(manifest, finding))
        elif finding.check == MISSING_DIRECTORY or finding.derived is None:
            actions.append(_remove_dead_entry(manifest, finding))
        else:
            actions.append(_rebuild_derived_fields(manifest, finding))
    return actions


def _check_entry(manifest: ProjectManifest, entry) -> ConsistencyFinding | None:
    from chipcompiler.cli.project.workspace_registration import WorkspaceRegistrationError

    path = entry.workspace_path
    if not os.path.isdir(path):
        return ConsistencyFinding(
            MISSING_DIRECTORY,
            entry.workspace_id,
            path,
            "workspace directory does not exist",
        )
    if entry.status == "archived":
        # Archival is a lifecycle decision, not a directory fact; only the
        # directory's existence is checked for archived entries.
        return None
    try:
        derived = _derive_fields(manifest, path)
    except (WorkspaceRegistrationError, ManifestError) as exc:
        return ConsistencyFinding(
            DERIVED_FIELD_MISMATCH,
            entry.workspace_id,
            path,
            f"workspace facts unreadable: {exc}",
        )
    mismatched = [
        field
        for field, current, wanted in (
            ("start_step", entry.start_step, derived.start_step),
            ("end_step", entry.end_step, derived.end_step),
            ("status", entry.status, derived.status),
            ("parameter_patch", entry.parameter_patch, derived.parameter_patch),
        )
        if current != wanted
    ]
    if not mismatched:
        return None
    return ConsistencyFinding(
        DERIVED_FIELD_MISMATCH,
        entry.workspace_id,
        path,
        f"derived fields disagree with directory facts: {', '.join(mismatched)}",
        derived=derived,
    )


def _derive_fields(manifest: ProjectManifest, workspace_path: str) -> DerivedFields:
    """Rebuild one entry's derived fields from the workspace directory.

    Uses the same inspection and range-mapping helpers as workspace
    registration, so a repaired entry equals what a fresh registration
    would write. Expectations and the parameter baseline come from the
    manifest itself, never from ecc.toml.
    """
    from chipcompiler.cli.project.workspace_registration import inspect_existing_workspace
    from chipcompiler.project.manifest_write import manifest_range_for_steps

    base_design = manifest.base_design
    metadata = inspect_existing_workspace(
        workspace_path,
        expected_design=manifest.design_name,
        expected_pdk=str(base_design.get("pdk") or ""),
        base_parameters=base_design.get("parameters") or {},
    )
    start_step, end_step = manifest_range_for_steps(
        metadata.flow_config["start_step"], metadata.flow_config["end_step"]
    )
    return DerivedFields(start_step, end_step, metadata.status, metadata.parameter_patch)


def _scan_unregistered(manifest: ProjectManifest) -> list[ConsistencyFinding]:
    from chipcompiler.cli.project.workspace_registration import is_ecc_workspace_directory

    project_dir = manifest.project_dir
    registered = {os.path.realpath(w.workspace_path) for w in manifest.workspaces}
    findings = []
    for name in sorted(os.listdir(project_dir)):
        if name == "runs":
            # The legacy runs/ container holds run directories, never one workspace.
            continue
        path = os.path.join(project_dir, name)
        if os.path.realpath(path) in registered:
            continue
        if is_ecc_workspace_directory(path):
            findings.append(
                ConsistencyFinding(
                    UNREGISTERED_DIRECTORY,
                    name,
                    path,
                    "workspace directory has no manifest entry",
                )
            )
    return findings


def _rebuild_derived_fields(manifest: ProjectManifest, finding: ConsistencyFinding) -> FixAction:
    derived = finding.derived
    assert derived is not None
    outcome = "rebuilt"
    detail = ""

    def mutate(document: dict) -> None:
        nonlocal outcome, detail
        entry = _find_entry(document, finding.workspace_id)
        if entry is None:
            outcome = "failed"
            detail = "manifest entry vanished before repair"
            return
        # apply_derived_fields never touches lineage and freezes archived
        # entries; only a real correction bumps updated_at, so a concurrent
        # fix stays a no-op.
        if apply_derived_fields(
            entry,
            {
                "start_step": derived.start_step,
                "end_step": derived.end_step,
                "status": derived.status,
                "parameter_patch": derived.parameter_patch,
            },
        ):
            now = _now_iso()
            entry["updated_at"] = now
            document["updated_at"] = now
        else:
            outcome = "unchanged"

    if not update_manifest(manifest.project_dir, mutate):
        outcome = "failed"
        detail = "manifest update failed"
    return FixAction(finding, outcome, detail)


def _remove_dead_entry(manifest: ProjectManifest, finding: ConsistencyFinding) -> FixAction:
    workspace_id = finding.workspace_id
    removed = False

    def mutate(document: dict) -> None:
        nonlocal removed
        entries = [e for e in document.get("workspaces", []) if isinstance(e, dict)]
        if not any(e.get("workspace_id") == workspace_id for e in entries):
            return
        removed = True
        # Mirrors the delete-workspace mutation: drop the entry and null
        # every reference (lineage, baseline, best) that pointed at it.
        document["workspaces"] = [e for e in entries if e.get("workspace_id") != workspace_id]
        for entry in document["workspaces"]:
            if entry.get("source_workspace_id") == workspace_id:
                entry["source_workspace_id"] = None
        for field in ("qor_baseline", "best_workspace"):
            selection = document.get(field)
            if isinstance(selection, dict) and selection.get("workspace_id") == workspace_id:
                document[field] = None
        document["updated_at"] = _now_iso()

    if not update_manifest(manifest.project_dir, mutate):
        return FixAction(finding, "failed", "manifest update failed")
    return FixAction(finding, "removed" if removed else "unchanged")


def _register_directory(manifest: ProjectManifest, finding: ConsistencyFinding) -> FixAction:
    from chipcompiler.cli.project.workspace_registration import (
        WorkspaceRegistrationError,
        import_managed_workspace,
    )

    base_design = manifest.base_design
    try:
        outcome, _metadata = import_managed_workspace(
            manifest.project_dir,
            design_name=manifest.design_name,
            workspace_id=finding.workspace_id,
            workspace_path=finding.workspace_path,
            expected_pdk=str(base_design.get("pdk") or ""),
            base_parameters=base_design.get("parameters") or {},
        )
    except WorkspaceRegistrationError as exc:
        return FixAction(finding, "failed", str(exc))
    if outcome in ("registered", "existing"):
        return FixAction(finding, outcome)
    return FixAction(finding, "failed", f"registration outcome: {outcome}")


def _find_entry(document: dict, workspace_id: str) -> dict | None:
    for entry in document.get("workspaces", []):
        if isinstance(entry, dict) and entry.get("workspace_id") == workspace_id:
            return entry
    return None
