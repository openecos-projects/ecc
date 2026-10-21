"""Project workspace registration checks and explicit repair.

The CLI owns execution state in workspace files and no longer synchronizes
cached range, status, or parameter fields in project.json. Doctor checks
directory existence, workspace readability, and unregistered directories.
Repair removes missing-directory entries and registers existing workspaces;
unreadable workspace files must be restored without deleting their registration.

Keep module-level imports cheap: this module sits on the CLI startup path.
"""

import os
from dataclasses import dataclass

from chipcompiler.project.manifest import ManifestError, ProjectManifest
from chipcompiler.project.manifest_write import _now_iso, update_manifest

INVALID_WORKSPACE = "invalid-workspace"
MISSING_DIRECTORY = "missing-directory"
UNREGISTERED_DIRECTORY = "unregistered-directory"


@dataclass(frozen=True)
class ConsistencyFinding:
    check: str
    workspace_id: str
    workspace_path: str
    detail: str


@dataclass(frozen=True)
class FixAction:
    finding: ConsistencyFinding
    action: str  # removed | registered | existing | unchanged | failed
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
        elif finding.check == MISSING_DIRECTORY:
            actions.append(_remove_dead_entry(manifest, finding))
        else:
            actions.append(
                FixAction(finding, "failed", "restore the workspace files before retrying")
            )
    return actions


def _check_entry(manifest: ProjectManifest, entry) -> ConsistencyFinding | None:
    from chipcompiler.cli.project.workspace_registration import (
        WorkspaceRegistrationError,
        inspect_existing_workspace,
    )
    from chipcompiler.project.runtime_processes import identity_is_live

    path = entry.workspace_path
    if not os.path.isdir(path):
        return ConsistencyFinding(
            MISSING_DIRECTORY,
            entry.workspace_id,
            path,
            "workspace directory does not exist",
        )
    if entry.status == "archived":
        return None
    runtime_entry = (manifest.raw.get("runtime_processes") or {}).get(entry.workspace_id)
    if isinstance(runtime_entry, dict):
        try:
            if identity_is_live(runtime_entry):
                # Live processes can be replacing workspace files during inspection.
                return None
        except Exception:
            # Invalid or stale registrations must be inspected like any other workspace.
            pass
    try:
        inspect_existing_workspace(
            path,
            expected_design=manifest.design_name,
            expected_pdk=str(manifest.base_design.get("pdk") or ""),
        )
    except (WorkspaceRegistrationError, ManifestError) as exc:
        return ConsistencyFinding(
            INVALID_WORKSPACE,
            entry.workspace_id,
            path,
            f"workspace facts unreadable: {exc}",
        )
    return None


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
