"""Publish a completed candidate as a managed Workspace without rerunning it."""

import re
import stat
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from chipcompiler.engine.workspace.derive import derive_workspace
from chipcompiler.project.api import project_manifest_mutator
from chipcompiler.project.manifest import load_manifest
from chipcompiler.project.manifest_write import manifest_lock, update_manifest_locked
from chipcompiler.utility.workspace_lock import workspace_lock

from .candidate_resume import _validate_candidate_resume_manifest
from .cli import _candidate_lock
from .data.candidate_artifacts import read_json_object, validate_candidate_id
from .operations import RuntimeOperationManager
from .workspace_api import (
    _CANDIDATE_WORKSPACE_MANIFEST,
    _required_file_sha256,
    candidate_operation_workspace_id,
)


def retain_candidate(
    *,
    project: Path,
    project_id: str,
    source: Path,
    workspace_id: str,
    candidate_id: str,
    digest: str,
    target_id: str,
) -> dict:
    candidate_id = validate_candidate_id(candidate_id)
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("Candidate manifest SHA-256 is invalid")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", target_id):
        raise ValueError("Workspace name must use letters, digits, underscores or hyphens")
    target = project / target_id
    if target.is_symlink() or target.with_suffix(".lock").is_symlink():
        raise ValueError("Target Workspace path is a symbolic link")
    ref = f".agent/candidates/{candidate_id}"
    candidate = source / ref
    ledgers = source / ".agent" / "operations"
    command_id = str(
        uuid5(NAMESPACE_URL, f"{project_id}:{workspace_id}:{candidate_id}:{digest}:{target_id}")
    )
    with (
        _candidate_lock(ledgers, candidate_id),
        workspace_lock(source, blocking=False),
        workspace_lock(target, blocking=False),
    ):
        if target.resolve() != target:
            raise ValueError("Target Workspace path is a symbolic link")
        current = load_manifest(str(project))
        entry = current.find_workspace(workspace_id)
        if (
            current.project_id != project_id
            or entry is None
            or Path(entry.workspace_path).resolve() != source
        ):
            raise ValueError("Source Workspace registration changed")
        existing = current.find_workspace(target_id)
        if existing is not None and Path(existing.workspace_path).resolve() != target:
            raise ValueError("Target Workspace name is already registered")
        evidence = _verify_completed_candidate(
            candidate, ref, digest, ledgers, workspace_id, candidate_id
        )
        derive_workspace(
            candidate,
            target,
            blocking=False,
            command_id=command_id,
            project_id=project_id,
            source_workspace_id=workspace_id,
            target_workspace_id=target_id,
            retained_candidate_sha256=digest,
            parent_workspace_directory=source,
            original_evidence=evidence,
            cause="workspace.candidate_retained",
        )
        mutation = {
            "type": "register_workspace",
            "workspace_id": target_id,
            "workspace_path": str(target),
            "source_workspace_id": workspace_id,
            "branch_from": {"source_workspace_id": workspace_id},
        }
        with manifest_lock(project, blocking=False):
            if load_manifest(str(project)).project_id != project_id:
                raise ValueError("Project identity changed")
            if not update_manifest_locked(project, project_manifest_mutator(project, mutation)):
                raise OSError("Could not register the retained Workspace")
    return {"workspaceId": target_id, "directory": str(target)}


def _verify_completed_candidate(
    candidate: Path,
    ref: str,
    digest: str,
    ledgers: Path,
    workspace_id: str,
    candidate_id: str,
) -> frozenset[Path]:
    if not candidate.is_dir() or candidate.resolve() != candidate:
        raise ValueError("Candidate artifacts are unavailable")
    for path in candidate.rglob("*"):
        mode = path.lstat().st_mode
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ValueError("Candidate contains an unsupported filesystem entry")

    manifest_path = candidate / "analysis" / _CANDIDATE_WORKSPACE_MANIFEST
    if _required_file_sha256(manifest_path, "manifest") != digest:
        raise ValueError("Candidate manifest no longer matches the Optimization Episode")
    manifest = read_json_object(manifest_path, "candidate manifest")
    _validate_candidate_resume_manifest(
        candidate.parents[2], candidate, ref, manifest, terminal_state="succeeded"
    )
    if not {"harden_gds", "harden_lef", "harden_lib"} <= manifest["artifacts"].keys():
        raise ValueError("Candidate Harden artifacts are incomplete")

    key = candidate_operation_workspace_id(workspace_id, candidate_id)
    manager = RuntimeOperationManager(lambda _event: None)
    manager.load_workspace_ledger(key, ledgers / f"{candidate_id}.json", recover=False)
    operations = manager.workspace_snapshot(key)["operations"]
    if not any(
        operation["state"] == "succeeded"
        and (operation["result"] or {}).get("candidateManifestSha256") == digest
        for operation in operations
    ):
        raise ValueError("ECC did not record a successful run for this candidate manifest")

    # Published evidence is historical and its checksums describe the original
    # candidate. Relocate active inputs and configs, preserving these bytes.
    return frozenset(
        {
            manifest_path.relative_to(candidate),
            Path("analysis/candidate_execution_receipt.v1.json"),
            Path("analysis/candidate_config_snapshots.v1"),
            *(Path(item["ref"]) for item in manifest["artifacts"].values()),
        }
    )
