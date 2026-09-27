import json
import shutil
from copy import deepcopy
from pathlib import Path

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.project.project_application import reconcile_project_state
from chipcompiler.engine import create_workspace_from_spec, update_workspace_from_spec
from chipcompiler.engine.snapshot import read_engineering_snapshot_from_directory
from chipcompiler.engine.workspace_derive import derive_workspace
from chipcompiler.engine.workspace_lifecycle import (
    _workspace_command_fingerprint,
    _write_workspace_command,
)
from chipcompiler.project import load_project_manifest, mutate_project_manifest


def _project_and_spec(tmp_path, minimal_ics55_pdk_factory):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    pdk = minimal_ics55_pdk_factory(tmp_path / "pdk")
    text = (project / "ecc.toml").read_text(encoding="utf-8")
    text = text.replace('name = ""', 'name = "ics55"', 1).replace(
        'root = ""', f'root = "{pdk}"', 1
    )
    (project / "ecc.toml").write_text(text, encoding="utf-8")
    fixture = Path(__file__).parents[2] / "fixtures" / "workspace_spec" / "valid.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    spec = payload["workspaceSpec"]
    bindings = deepcopy(payload["workspaceBindings"])
    bindings["inputs"] = {
        key: str(fixture.parent / value) for key, value in bindings["inputs"].items()
    }
    bindings["pdk"]["root"] = str(pdk)
    return project, spec, bindings


def _register(project: Path, workspace_id: str) -> Path:
    workspace = project / workspace_id
    mutate_project_manifest(
        project,
        {
            "type": "register_workspace",
            "workspace_id": workspace_id,
            "workspace_path": str(workspace),
        },
    )
    return workspace


def test_reconcile_registers_a_proven_create_orphan(
    tmp_path, minimal_ics55_pdk_factory
):
    project, spec, bindings = _project_and_spec(tmp_path, minimal_ics55_pdk_factory)
    target = project / "created"
    create_workspace_from_spec(target, spec, bindings)
    snapshot = read_engineering_snapshot_from_directory(target)
    request = {"workspace": "created", "from": None, "to": None, "parameters": []}
    command_id = "create-crash-1"
    _write_workspace_command(
        target,
        command_id,
        _workspace_command_fingerprint("create", request, None, None),
        snapshot["workspaceId"],
        snapshot["workspaceRevision"],
        metadata={
            "operation": "create",
            "projectId": load_project_manifest(project)["project_id"],
            "workspaceId": "created",
            "workspacePath": str(target.resolve()),
            "request": request,
            "expectedRevision": None,
        },
    )

    report = reconcile_project_state(project, blocking=True)

    assert report.errors == ()
    assert "orphan_workspace:created" in report.repairs
    assert load_project_manifest(project)["workspaces"][0]["workspace_id"] == "created"


def test_reconcile_registers_a_proven_derive_orphan(
    tmp_path, minimal_ics55_pdk_factory
):
    project, spec, bindings = _project_and_spec(tmp_path, minimal_ics55_pdk_factory)
    source = project / "source"
    create_workspace_from_spec(source, spec, bindings, "source-create")
    _register(project, "source")
    project_id = load_project_manifest(project)["project_id"]
    target = project / "branch"
    derive_workspace(
        source,
        target,
        command_id="derive-crash-1",
        project_id=project_id,
        source_workspace_id="source",
        target_workspace_id="branch",
    )

    report = reconcile_project_state(project, blocking=True)

    assert report.errors == ()
    assert "orphan_workspace:branch" in report.repairs
    branch = next(
        entry
        for entry in load_project_manifest(project)["workspaces"]
        if entry["workspace_id"] == "branch"
    )
    assert branch["source_workspace_id"] == "source"


def test_reconcile_cleans_a_proven_post_exchange_refresh_staging(
    tmp_path, minimal_ics55_pdk_factory
):
    project, spec, bindings = _project_and_spec(tmp_path, minimal_ics55_pdk_factory)
    workspace = project / "baseline"
    create_workspace_from_spec(workspace, spec, bindings, "create-1")
    _register(project, "baseline")
    staging = project / ".baseline.staging-crash"
    shutil.copytree(workspace, staging)
    update_workspace_from_spec(workspace, 1, spec, bindings, "refresh-1")

    report = reconcile_project_state(project, blocking=True)

    assert report.errors == ()
    assert "refresh_exchange:baseline" in report.repairs
    assert not staging.exists()
    assert read_engineering_snapshot_from_directory(workspace)["workspaceRevision"] == 2


def test_reconcile_rolls_forward_a_portable_refresh_with_missing_target(
    tmp_path, minimal_ics55_pdk_factory
):
    project, spec, bindings = _project_and_spec(tmp_path, minimal_ics55_pdk_factory)
    workspace = project / "baseline"
    create_workspace_from_spec(workspace, spec, bindings, "create-1")
    _register(project, "baseline")
    old_staging = project / ".baseline.staging-crash"
    shutil.copytree(workspace, old_staging)
    update_workspace_from_spec(workspace, 1, spec, bindings, "refresh-1")

    backup = Path(f"{old_staging}.exchange-old")
    old_staging.rename(backup)
    workspace.rename(old_staging)

    report = reconcile_project_state(project, blocking=True)

    assert report.errors == ()
    assert "refresh_exchange:baseline" in report.repairs
    assert workspace.is_dir()
    assert not old_staging.exists()
    assert not backup.exists()
    assert read_engineering_snapshot_from_directory(workspace)["workspaceRevision"] == 2
