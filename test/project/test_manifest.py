import json

from chipcompiler.cli.project.manifest import load_manifest
from chipcompiler.project import (
    create_project_manifest,
    discover_project_manifest,
    load_project_manifest,
    mutate_project_manifest,
)


def test_domain_created_manifest_is_cli_readable(tmp_path):
    created = create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")

    loaded = load_manifest(str(tmp_path))

    assert created["root_path"] == str(tmp_path.resolve())
    assert loaded.project_id == created["project_id"]
    assert loaded.design_name == "gcd"
    assert loaded.workspaces == ()


def test_project_manifest_is_discovered_from_nested_workspace(tmp_path):
    workspace = tmp_path / "experiment"
    workspace.mkdir()
    created = create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")

    assert discover_project_manifest(workspace) == (tmp_path.resolve(), created)


def test_register_workspace_uses_main_manifest_shape(tmp_path):
    workspace = tmp_path / "experiment"
    (workspace / "home").mkdir(parents=True)
    (workspace / "home" / "flow.json").write_text(
        json.dumps({"steps": [{"name": "Synthesis", "state": "Unstart"}]})
    )
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")

    updated = mutate_project_manifest(
        tmp_path,
        {
            "type": "register_workspace",
            "workspace_id": "experiment",
            "workspace_path": str(workspace),
            "name": "Experiment",
            "created_at": "2026-02-01T00:00:00Z",
            "updated_at": "2026-02-01T00:00:00Z",
        },
    )

    assert updated == load_project_manifest(tmp_path)
    assert updated["workspaces"][0]["start_step"] == "Synth"
    assert updated["workspaces"][0]["end_step"] == "Synth"


def test_manifest_mutation_without_timestamp_keeps_audit_timestamp(tmp_path):
    workspace = tmp_path / "experiment"
    (workspace / "home").mkdir(parents=True)
    (workspace / "home" / "flow.json").write_text(json.dumps({"steps": []}))
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    mutate_project_manifest(
        tmp_path,
        {
            "type": "register_workspace",
            "workspace_id": "experiment",
            "workspace_path": str(workspace),
            "name": "Experiment",
        },
    )

    updated = mutate_project_manifest(
        tmp_path,
        {"type": "archive_workspace", "workspace_id": "experiment"},
    )

    assert updated["updated_at"]
    assert updated["workspaces"][0]["updated_at"]
