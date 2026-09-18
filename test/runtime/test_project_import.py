import json

import pytest

from chipcompiler.data.parameter import Parameters, save_parameter
from chipcompiler.project import create_project_manifest
from chipcompiler.runtime.errors import RuntimeApiError
from chipcompiler.runtime.requests import ProjectManifestMutationRequest
from chipcompiler.runtime.workspace_api import WorkspaceRuntimeApi


def _existing_workspace(path, *, design="gcd", pdk="ics55", state="Success"):
    home = path / "home"
    home.mkdir(parents=True)
    (home / "flow.json").write_text(
        json.dumps({"steps": [{"name": "Synthesis", "tool": "yosys", "state": state}]})
    )
    assert save_parameter(
        Parameters(
            path=home / "params.toml",
            data={
                "pdk": pdk,
                "design": design,
                "top_module": design,
                "clock": "clk",
                "frequency_max": 125,
                "_flow": {"start": "Synthesis", "end": "Synthesis"},
            },
        )
    )


def _import(api, project_dir, workspace):
    return api.mutate_project_manifest(
        ProjectManifestMutationRequest(
            project_root=str(project_dir),
            mutation={
                "type": "import-workspace",
                "input": {"projectRoot": str(project_dir), "workspacePath": str(workspace)},
            },
        )
    )


def test_import_workspace_registers_external_workspace(tmp_path):
    project_dir = tmp_path / "proj"
    create_project_manifest(project_dir, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    workspace = tmp_path / "external" / "recovered"
    _existing_workspace(workspace)

    manifest = _import(WorkspaceRuntimeApi(), project_dir, workspace)

    (entry,) = manifest["workspaces"]
    assert entry["workspace_id"] == "recovered"
    assert entry["workspace_path"] == str(workspace.resolve())
    assert entry["start_step"] == "Synth"
    assert entry["end_step"] == "Synth"
    assert entry["status"] == "success"


def test_import_workspace_is_idempotent_for_the_same_path(tmp_path):
    project_dir = tmp_path / "proj"
    create_project_manifest(project_dir, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    workspace = tmp_path / "external" / "recovered"
    _existing_workspace(workspace)
    api = WorkspaceRuntimeApi()

    first = _import(api, project_dir, workspace)
    second = _import(api, project_dir, workspace)

    assert [entry["workspace_id"] for entry in second["workspaces"]] == ["recovered"]
    assert second["workspaces"] == first["workspaces"]


def test_import_workspace_rejects_design_mismatch(tmp_path):
    project_dir = tmp_path / "proj"
    create_project_manifest(project_dir, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    workspace = tmp_path / "external" / "recovered"
    _existing_workspace(workspace, design="other")

    with pytest.raises(RuntimeApiError) as excinfo:
        _import(WorkspaceRuntimeApi(), project_dir, workspace)

    assert excinfo.value.code == "workspace_not_importable"


def test_import_workspace_rejects_non_workspace_directory(tmp_path):
    project_dir = tmp_path / "proj"
    create_project_manifest(project_dir, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    workspace = tmp_path / "external" / "recovered"
    workspace.mkdir(parents=True)

    with pytest.raises(RuntimeApiError) as excinfo:
        _import(WorkspaceRuntimeApi(), project_dir, workspace)

    assert excinfo.value.code == "workspace_not_importable"


def test_import_workspace_distinguishes_id_and_path_conflicts(tmp_path):
    project_dir = tmp_path / "proj"
    create_project_manifest(project_dir, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    first = tmp_path / "external" / "recovered"
    _existing_workspace(first)
    api = WorkspaceRuntimeApi()
    _import(api, project_dir, first)

    same_id_elsewhere = tmp_path / "elsewhere" / "recovered"
    _existing_workspace(same_id_elsewhere)
    with pytest.raises(RuntimeApiError) as excinfo:
        _import(api, project_dir, same_id_elsewhere)
    assert excinfo.value.code == "workspace_id_conflict"

    with pytest.raises(RuntimeApiError) as excinfo:
        api.mutate_project_manifest(
            ProjectManifestMutationRequest(
                project_root=str(project_dir),
                mutation={
                    "type": "import-workspace",
                    "input": {
                        "projectRoot": str(project_dir),
                        "workspacePath": str(first),
                        "workspaceId": "renamed",
                    },
                },
            )
        )
    assert excinfo.value.code == "workspace_path_conflict"
