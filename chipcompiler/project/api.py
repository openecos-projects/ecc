import json
import shutil
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from chipcompiler.cli.project.manifest import (
    _CANONICAL_TO_MANIFEST_STEP,
    ManifestError,
    load_manifest,
)
from chipcompiler.cli.project.manifest_write import (
    build_project_document,
    manifest_workspace_entry,
    update_manifest,
    write_manifest_if_absent,
)


def load_project_manifest(project_dir: str | Path) -> dict:
    manifest = load_manifest(str(Path(project_dir).expanduser().resolve()))
    document = deepcopy(manifest.raw)
    document.update(
        {
            "schema_version": 1,
            "project_id": manifest.project_id,
            "name": manifest.name,
            "design_name": manifest.design_name,
            "root_path": manifest.project_dir,
            "base_design": deepcopy(manifest.base_design),
            "objectives": deepcopy(manifest.objectives),
            "workspaces": [_workspace_document(item) for item in manifest.workspaces],
            "qor_baseline": deepcopy(manifest.qor_baseline),
        }
    )
    return document


def discover_project_manifest(directory: str | Path) -> tuple[Path, dict] | None:
    current = Path(directory).expanduser().resolve()
    if not current.is_dir():
        current = current.parent
    for project in (current, *current.parents):
        if (project / "project.json").exists() or (project / "project.json").is_symlink():
            return project, load_project_manifest(project)
    return None


def create_project_manifest(
    project_dir: str | Path,
    name: str,
    design_name: str,
    *,
    now: str | None = None,
    mpc: dict | None = None,
) -> dict:
    project = Path(project_dir).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    document = build_project_document(
        str(project),
        design_name=design_name,
        base_design={"rtl_list": [], "parameters": {"design": design_name}},
        name=name,
        now=now,
        mpc=mpc,
    )
    if not write_manifest_if_absent(str(project), document):
        raise ManifestError(f"Project Manifest already exists: {project / 'project.json'}")
    try:
        return load_project_manifest(project)
    except Exception:
        (project / "project.json").unlink(missing_ok=True)
        raise


def mutate_project_manifest(project_dir: str | Path, mutation: dict) -> dict:
    project = Path(project_dir).expanduser().resolve()
    load_project_manifest(project)

    def apply(document: dict) -> None:
        kind = mutation.get("type")
        if kind == "register_workspace":
            _register_workspace(document, mutation, project)
        elif kind in {"select_qor_baseline", "select_best_workspace"}:
            _select_workspace(document, mutation)
        elif kind == "archive_workspace":
            _archive_workspace(document, mutation)
        elif kind == "delete_workspace":
            _delete_workspace(document, mutation)
        else:
            raise ManifestError(f"unsupported Project mutation: {kind}")

    if not update_manifest(str(project), apply):
        raise ManifestError("Project Manifest update failed")
    return load_project_manifest(project)


def create_project_workspace(
    project_dir: str | Path,
    target_directory: str | Path,
    spec: object,
    bindings: object,
    *,
    command_id: str,
    workspace_id: str | None = None,
    name: str | None = None,
    source_workspace_id: str | None = None,
    expected_project_id: str | None = None,
    now: str | None = None,
):
    from chipcompiler.engine import create_workspace_from_spec

    project = Path(project_dir).expanduser().resolve()
    target = Path(target_directory).expanduser().resolve()
    try:
        target.relative_to(project)
    except ValueError as exc:
        raise ManifestError("Workspace must be inside the Project root") from exc
    manifest = load_project_manifest(project)
    if expected_project_id is not None and manifest["project_id"] != expected_project_id:
        raise ManifestError("Project identity does not match")
    existed = target.exists()
    workspace = create_workspace_from_spec(str(target), spec, bindings, command_id)
    if workspace is None:
        raise ManifestError("Workspace creation returned no Workspace")
    identity = workspace_id or target.name
    try:
        mutate_project_manifest(
            project,
            {
                "type": "register_workspace",
                "workspace_id": identity,
                "name": name or identity,
                "workspace_path": str(target),
                "source_workspace_id": source_workspace_id,
                "created_at": now,
                "updated_at": now,
            },
        )
    except Exception:
        if not existed:
            shutil.rmtree(target, ignore_errors=True)
        raise
    return workspace


def _workspace_document(workspace) -> dict:
    document = deepcopy(workspace.raw)
    document.update(
        {
            "workspace_id": workspace.workspace_id,
            "workspace_path": workspace.workspace_path,
            "start_step": workspace.start_step,
            "end_step": workspace.end_step,
            "status": workspace.status,
            "parameter_patch": deepcopy(workspace.parameter_patch),
        }
    )
    return document


def _register_workspace(document: dict, mutation: dict, project: Path) -> None:
    workspace_id = _required_string(mutation, "workspace_id")
    workspace_path = _resolve_workspace(project, _required_string(mutation, "workspace_path"))
    for existing in document.get("workspaces", []):
        same_id = existing.get("workspace_id") == workspace_id
        same_path = (
            _resolve_workspace(project, str(existing.get("workspace_path", ""))) == workspace_path
        )
        if same_id and same_path:
            return
        if same_id or same_path:
            raise ManifestError(f"Workspace registration conflicts with: {workspace_id}")
    start_step, end_step = _workspace_range(workspace_path, mutation)
    timestamp = str(
        mutation.get("updated_at") or mutation.get("created_at") or datetime.now(UTC).isoformat()
    )
    entry = manifest_workspace_entry(
        workspace_id,
        name=str(mutation.get("name") or workspace_id),
        workspace_path=str(workspace_path),
        start_step=start_step,
        end_step=end_step,
        status="archived" if mutation.get("lifecycle") == "archived" else "not_started",
        now=timestamp,
    )
    for key in (
        "source_workspace_id",
        "branch_from",
        "parameter_patch",
        "metrics_summary",
        "step_metrics",
    ):
        if key in mutation:
            entry[key] = deepcopy(mutation[key])
    document.setdefault("workspaces", []).append(entry)
    document["updated_at"] = timestamp


def _workspace_range(workspace: Path, mutation: dict) -> tuple[str, str]:
    start = mutation.get("start_step")
    end = mutation.get("end_step")
    if isinstance(start, str) and isinstance(end, str) and start and end:
        return start, end
    try:
        ledger = json.loads((workspace / "home" / "flow.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "Synth", "Harden"
    names = [
        step.get("name")
        for step in ledger.get("steps", [])
        if isinstance(step, dict) and isinstance(step.get("name"), str)
    ]
    if not names:
        return "Synth", "Harden"
    return (
        _CANONICAL_TO_MANIFEST_STEP.get(names[0], names[0]),
        _CANONICAL_TO_MANIFEST_STEP.get(names[-1], names[-1]),
    )


def _select_workspace(document: dict, mutation: dict) -> None:
    workspace_id = _required_string(mutation, "workspace_id")
    workspace = _find_workspace(document, workspace_id)
    if workspace.get("status") == "archived":
        raise ManifestError(f"Workspace is not active: {workspace_id}")
    field = "qor_baseline" if mutation["type"] == "select_qor_baseline" else "best_workspace"
    document[field] = {"workspace_id": workspace_id, "reason": str(mutation.get("reason") or "")}
    document["updated_at"] = str(mutation.get("updated_at") or datetime.now(UTC).isoformat())


def _archive_workspace(document: dict, mutation: dict) -> None:
    workspace = _find_workspace(document, _required_string(mutation, "workspace_id"))
    workspace["status"] = "archived"
    timestamp = str(mutation.get("updated_at") or datetime.now(UTC).isoformat())
    workspace["updated_at"] = timestamp
    document["updated_at"] = timestamp


def _delete_workspace(document: dict, mutation: dict) -> None:
    workspace_id = _required_string(mutation, "workspace_id")
    _find_workspace(document, workspace_id)
    document["workspaces"] = [
        workspace
        for workspace in document.get("workspaces", [])
        if workspace.get("workspace_id") != workspace_id
    ]
    for workspace in document["workspaces"]:
        if workspace.get("source_workspace_id") == workspace_id:
            workspace["source_workspace_id"] = None
    for field in ("qor_baseline", "best_workspace"):
        selection = document.get(field)
        if isinstance(selection, dict) and selection.get("workspace_id") == workspace_id:
            document[field] = None
    document["updated_at"] = str(mutation.get("updated_at") or datetime.now(UTC).isoformat())


def _find_workspace(document: dict, workspace_id: str) -> dict:
    for workspace in document.get("workspaces", []):
        if isinstance(workspace, dict) and workspace.get("workspace_id") == workspace_id:
            return workspace
    raise ManifestError(f"Workspace is not registered: {workspace_id}")


def _required_string(value: dict, key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ManifestError(f"Project Manifest {key} is required")
    return result.strip()


def _resolve_workspace(project: Path, declared: str) -> Path:
    workspace = Path(declared)
    workspace = workspace if workspace.is_absolute() else project / workspace
    resolved = workspace.resolve()
    try:
        resolved.relative_to(project)
    except ValueError as exc:
        raise ManifestError("Workspace must be inside the Project root") from exc
    return resolved
