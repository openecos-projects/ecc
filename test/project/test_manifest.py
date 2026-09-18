import json
from contextlib import contextmanager

import chipcompiler.project.api as project_api
from chipcompiler.cli.project.manifest import load_manifest
from chipcompiler.project import (
    create_project_manifest,
    discover_project_manifest,
    load_project_manifest,
    mutate_project_manifest,
)
from chipcompiler.project.manifest_write import append_workspace_entry


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


def test_register_workspace_allows_existing_external_workspace(tmp_path):
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    external = tmp_path.parent / "external" / "workspace"
    assert (
        append_workspace_entry(
            str(tmp_path),
            workspace_id="external",
            name="External",
            workspace_path=str(external),
            start_step="Synth",
            end_step="Harden",
            status="success",
        )
        == "registered"
    )

    updated = mutate_project_manifest(
        tmp_path,
        {
            "type": "register_workspace",
            "workspace_id": "ws_0009",
            "workspace_path": str(tmp_path / "ws_0009"),
            "name": "ws_0009",
        },
    )

    assert [entry["workspace_id"] for entry in updated["workspaces"]] == [
        "external",
        "ws_0009",
    ]


def test_reregister_workspace_completes_lineage_fields(tmp_path):
    workspace = tmp_path / "ws_0009"
    (workspace / "home").mkdir(parents=True)
    (workspace / "home" / "flow.json").write_text(
        json.dumps({"steps": [{"name": "PostFloorplan", "state": "Unstart"}]})
    )
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    registered = mutate_project_manifest(
        tmp_path,
        {
            "type": "register_workspace",
            "workspace_id": "ws_0009",
            "workspace_path": str(workspace),
            "name": "ws_0009",
            "source_workspace_id": None,
            "created_at": "2026-02-01T00:00:00Z",
            "updated_at": "2026-02-01T00:00:00Z",
        },
    )
    assert registered["workspaces"][0]["source_workspace_id"] is None

    branch_from = {
        "source_workspace_id": "ws_0002",
        "source_step": "Floor",
        "source_output_path": str(tmp_path / "ws_0002" / "floorplan" / "outputs" / "gcd.def"),
        "source_output_type": "def",
    }
    updated = mutate_project_manifest(
        tmp_path,
        {
            "type": "register_workspace",
            "workspace_id": "ws_0009",
            "workspace_path": str(workspace),
            "name": "ws_0009",
            "source_workspace_id": "ws_0002",
            "branch_from": branch_from,
            "updated_at": "2026-03-01T00:00:00Z",
        },
    )

    entry = updated["workspaces"][0]
    assert entry["source_workspace_id"] == "ws_0002"
    assert entry["branch_from"] == branch_from
    assert entry["start_step"] == "PostFloorplan"
    assert entry["updated_at"] == "2026-03-01T00:00:00Z"

    # A later registration without lineage metadata must not clear it.
    reregistered = mutate_project_manifest(
        tmp_path,
        {
            "type": "register_workspace",
            "workspace_id": "ws_0009",
            "workspace_path": str(workspace),
            "source_workspace_id": None,
            "updated_at": "2026-04-01T00:00:00Z",
        },
    )
    entry = reregistered["workspaces"][0]
    assert entry["source_workspace_id"] == "ws_0002"
    assert entry["branch_from"] == branch_from


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


def test_project_workspace_acquires_manifest_lock_before_workspace_lock(tmp_path, monkeypatch):
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    events = []

    @contextmanager
    def marked_lock(name):
        events.append(f"{name}:acquire")
        yield

    monkeypatch.setattr(project_api, "manifest_lock", lambda _project: marked_lock("manifest"))
    monkeypatch.setattr(
        "chipcompiler.engine.reconcile._workspace_lock",
        lambda _target: marked_lock("workspace"),
    )
    monkeypatch.setattr(
        "chipcompiler.engine.workspace_lifecycle._create_workspace_from_spec",
        lambda *_args: object(),
    )
    monkeypatch.setattr(project_api, "update_manifest_locked", lambda *_args: True)

    project_api.create_project_workspace(
        tmp_path,
        tmp_path / "experiment",
        {},
        {},
        command_id="create-1",
    )

    assert events == ["manifest:acquire", "workspace:acquire"]
