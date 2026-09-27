import json
from contextlib import contextmanager

import pytest

import chipcompiler.project.api as project_api
from chipcompiler.cli.project.manifest import load_manifest
from chipcompiler.project import (
    create_project_manifest,
    discover_project_manifest,
    load_project_manifest,
    mutate_project_manifest,
    register_workspace_backup,
    repoint_generation_pointers,
)
from chipcompiler.project.manifest import ManifestError
from chipcompiler.project.manifest_refresh import refresh_workspace_derived_fields
from chipcompiler.project.manifest_write import append_workspace_entry, write_back_workspace_status


def _write_workspace_facts(workspace, *, steps, parameters):
    """Materialize workspace directory facts: home/flow.json + home/params.toml."""
    from chipcompiler.data.parameter import Parameters, save_parameter

    home = workspace / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "flow.json").write_text(json.dumps({"steps": steps}))
    assert save_parameter(Parameters(path=home / "params.toml", data=parameters))


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


def test_register_workspace_canonicalizes_studio_display_step_names(tmp_path):
    workspace = tmp_path / "ws_rerun"
    (workspace / "home").mkdir(parents=True)
    (workspace / "home" / "flow.json").write_text(
        json.dumps({"steps": [{"name": "postRouteLec", "state": "Unstart"}]})
    )
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")

    updated = mutate_project_manifest(
        tmp_path,
        {
            "type": "register_workspace",
            "workspace_id": "ws_rerun",
            "workspace_path": str(workspace),
            "start_step": "Timing Opt",
            "end_step": "Post-route LEC",
            "created_at": "2026-02-01T00:00:00Z",
            "updated_at": "2026-02-01T00:00:00Z",
        },
    )

    assert updated == load_project_manifest(tmp_path)
    assert updated["workspaces"][0]["start_step"] == "TimingOpt"
    assert updated["workspaces"][0]["end_step"] == "PostRouteLEC"


def test_manifest_with_studio_display_step_names_still_loads(tmp_path):
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    manifest_path = tmp_path / "project.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["workspaces"].append(
        {
            "workspace_id": "ws_legacy",
            "workspace_path": "ws_legacy",
            "start_step": "Post-route LEC",
            "end_step": "Post-route LEC",
            "status": "not_started",
        }
    )
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    loaded = load_project_manifest(tmp_path)

    assert loaded["workspaces"][0]["start_step"] == "PostRouteLEC"
    assert loaded["workspaces"][0]["end_step"] == "PostRouteLEC"


def test_register_workspace_rejects_unknown_step_without_poisoning_manifest(tmp_path):
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")

    with pytest.raises(ManifestError, match="not on the canonical flow chain"):
        mutate_project_manifest(
            tmp_path,
            {
                "type": "register_workspace",
                "workspace_id": "ws_bad",
                "workspace_path": str(tmp_path / "ws_bad"),
                "start_step": "Spin",
                "end_step": "Spin",
            },
        )

    assert load_manifest(str(tmp_path)).workspaces == ()


def test_register_workspace_rejects_reversed_range(tmp_path):
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")

    with pytest.raises(ManifestError, match="reversed"):
        mutate_project_manifest(
            tmp_path,
            {
                "type": "register_workspace",
                "workspace_id": "ws_rev",
                "workspace_path": str(tmp_path / "ws_rev"),
                "start_step": "Harden",
                "end_step": "Synth",
            },
        )


def test_power_analysis_bounds_the_flow_range_between_sta_and_lvs(tmp_path):
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    manifest_path = tmp_path / "project.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["workspaces"].append(
        {
            "workspace_id": "ws_sta_power",
            "workspace_path": "ws_sta_power",
            "start_step": "STA",
            "end_step": "PowerAnalysis",
            "status": "not_started",
        }
    )
    document["workspaces"].append(
        {
            "workspace_id": "ws_power_lvs",
            "workspace_path": "ws_power_lvs",
            "start_step": "PowerAnalysis",
            "end_step": "LVS",
            "status": "not_started",
        }
    )
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    loaded = load_project_manifest(tmp_path)

    assert (loaded["workspaces"][0]["start_step"], loaded["workspaces"][0]["end_step"]) == (
        "STA",
        "PowerAnalysis",
    )
    assert (loaded["workspaces"][1]["start_step"], loaded["workspaces"][1]["end_step"]) == (
        "PowerAnalysis",
        "LVS",
    )


def test_power_analysis_cannot_precede_sta_in_a_flow_range(tmp_path):
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    manifest_path = tmp_path / "project.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["workspaces"].append(
        {
            "workspace_id": "ws_reversed",
            "workspace_path": "ws_reversed",
            "start_step": "PowerAnalysis",
            "end_step": "STA",
            "status": "not_started",
        }
    )
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ManifestError, match="reversed"):
        load_project_manifest(tmp_path)


def test_power_analysis_display_name_self_heals_to_manifest_spelling(tmp_path):
    workspace = tmp_path / "ws_power"
    (workspace / "home").mkdir(parents=True)
    (workspace / "home" / "flow.json").write_text(
        json.dumps({"steps": [{"name": "powerAnalysis", "state": "Unstart"}]})
    )
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")

    updated = mutate_project_manifest(
        tmp_path,
        {
            "type": "register_workspace",
            "workspace_id": "ws_power",
            "workspace_path": str(workspace),
            "start_step": "Power Analysis",
            "end_step": "Power Analysis",
            "created_at": "2026-02-01T00:00:00Z",
            "updated_at": "2026-02-01T00:00:00Z",
        },
    )

    assert updated == load_project_manifest(tmp_path)
    assert updated["workspaces"][0]["start_step"] == "PowerAnalysis"
    assert updated["workspaces"][0]["end_step"] == "PowerAnalysis"


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


def test_reregister_workspace_silently_corrects_derived_fields(tmp_path):
    workspace = tmp_path / "ws_0009"
    _write_workspace_facts(
        workspace,
        steps=[{"name": "Synthesis", "tool": "yosys", "state": "Success"}],
        parameters={
            "pdk": "ics55",
            "design": "gcd",
            "top_module": "gcd",
            "clock": "clk",
            "frequency_max": 125,
            "_flow": {"start": "Synthesis", "end": "Synthesis"},
        },
    )
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    branch_from = {
        "source_workspace_id": "ws_0002",
        "source_step": "Floor",
        "source_output_path": str(tmp_path / "ws_0002" / "floorplan" / "outputs" / "gcd.def"),
        "source_output_type": "def",
    }
    registered = mutate_project_manifest(
        tmp_path,
        {
            "type": "register_workspace",
            "workspace_id": "ws_0009",
            "workspace_path": str(workspace),
            "name": "ws_0009",
            "source_workspace_id": "ws_0002",
            "branch_from": branch_from,
            "updated_at": "2026-02-01T00:00:00Z",
        },
    )
    entry = registered["workspaces"][0]
    assert entry["status"] == "not_started"
    assert entry["parameter_patch"] == {}

    # Re-registration with stale derived fields: silently corrected from the
    # directory, only updated_at records it, lineage is never rewritten.
    corrected = mutate_project_manifest(
        tmp_path,
        {
            "type": "register_workspace",
            "workspace_id": "ws_0009",
            "workspace_path": str(workspace),
            "updated_at": "2026-03-01T00:00:00Z",
        },
    )
    entry = corrected["workspaces"][0]
    assert entry["start_step"] == "Synth"
    assert entry["end_step"] == "Synth"
    assert entry["status"] == "success"
    assert entry["parameter_patch"] == {"frequency_max": {"from": None, "to": 125}}
    assert entry["updated_at"] == "2026-03-01T00:00:00Z"
    assert entry["source_workspace_id"] == "ws_0002"
    assert entry["branch_from"] == branch_from

    # The workspace changed in place (new generation): the next
    # re-registration re-converges every derived field on the new facts.
    _write_workspace_facts(
        workspace,
        steps=[
            {"name": "CTS", "tool": "ecc", "state": "Unstart"},
            {"name": "route", "tool": "ecc", "state": "Unstart"},
        ],
        parameters={
            "pdk": "ics55",
            "design": "gcd",
            "top_module": "gcd",
            "clock": "clk",
            "_flow": {"start": "CTS", "end": "route"},
        },
    )
    refreshed = mutate_project_manifest(
        tmp_path,
        {
            "type": "register_workspace",
            "workspace_id": "ws_0009",
            "workspace_path": str(workspace),
            "updated_at": "2026-04-01T00:00:00Z",
        },
    )
    entry = refreshed["workspaces"][0]
    assert entry["start_step"] == "CTS"
    assert entry["end_step"] == "Route"
    assert entry["status"] == "not_started"
    assert entry["parameter_patch"] == {}
    assert entry["updated_at"] == "2026-04-01T00:00:00Z"
    assert entry["source_workspace_id"] == "ws_0002"
    assert entry["branch_from"] == branch_from


def test_reregister_workspace_without_drift_keeps_updated_at(tmp_path):
    workspace = tmp_path / "ws_0009"
    _write_workspace_facts(
        workspace,
        steps=[{"name": "Synthesis", "tool": "yosys", "state": "Success"}],
        parameters={
            "pdk": "ics55",
            "design": "gcd",
            "top_module": "gcd",
            "clock": "clk",
            "_flow": {"start": "Synthesis", "end": "Synthesis"},
        },
    )
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    mutation = {
        "type": "register_workspace",
        "workspace_id": "ws_0009",
        "workspace_path": str(workspace),
        "name": "ws_0009",
    }
    mutate_project_manifest(tmp_path, {**mutation, "updated_at": "2026-02-01T00:00:00Z"})
    # First re-registration converges the derived fields on the directory.
    mutate_project_manifest(tmp_path, {**mutation, "updated_at": "2026-03-01T00:00:00Z"})

    # A consistent re-registration is a pure no-op: no updated_at bump.
    reregistered = mutate_project_manifest(
        tmp_path, {**mutation, "updated_at": "2026-04-01T00:00:00Z"}
    )

    entry = reregistered["workspaces"][0]
    assert entry["status"] == "success"
    assert entry["updated_at"] == "2026-03-01T00:00:00Z"


def test_refresh_workspace_derived_fields_realigns_entry_with_directory(tmp_path):
    workspace = tmp_path / "ws_0001"
    _write_workspace_facts(
        workspace,
        steps=[{"name": "Synthesis", "tool": "yosys", "state": "Success"}],
        parameters={
            "pdk": "ics55",
            "design": "gcd",
            "top_module": "gcd",
            "clock": "clk",
            "frequency_max": 125,
            "_flow": {"start": "Synthesis", "end": "Synthesis"},
        },
    )
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    mutate_project_manifest(
        tmp_path,
        {
            "type": "register_workspace",
            "workspace_id": "ws_0001",
            "workspace_path": str(workspace),
            "source_workspace_id": "ws_0000",
            "updated_at": "2026-02-01T00:00:00Z",
        },
    )
    assert write_back_workspace_status(str(tmp_path), "ws_0001", "success") is True

    # An in-place update replaces the directory facts: new range, fresh
    # (never-run) ledger, parameters back to the project base.
    _write_workspace_facts(
        workspace,
        steps=[
            {"name": "CTS", "tool": "ecc", "state": "Unstart"},
            {"name": "route", "tool": "ecc", "state": "Unstart"},
        ],
        parameters={
            "pdk": "ics55",
            "design": "gcd",
            "top_module": "gcd",
            "clock": "clk",
            "_flow": {"start": "CTS", "end": "route"},
        },
    )

    assert refresh_workspace_derived_fields(str(tmp_path), "ws_0001") is True

    entry = load_project_manifest(tmp_path)["workspaces"][0]
    assert entry["start_step"] == "CTS"
    assert entry["end_step"] == "Route"
    # A new-generation workspace has never run: not_started.
    assert entry["status"] == "not_started"
    assert entry["parameter_patch"] == {}
    assert entry["updated_at"] != "2026-02-01T00:00:00Z"
    assert entry["source_workspace_id"] == "ws_0000"


def test_refresh_workspace_derived_fields_freezes_archived_entries(tmp_path):
    workspace = tmp_path / "ws_0001"
    _write_workspace_facts(
        workspace,
        steps=[{"name": "CTS", "tool": "ecc", "state": "Unstart"}],
        parameters={
            "pdk": "ics55",
            "design": "gcd",
            "top_module": "gcd",
            "clock": "clk",
            "_flow": {"start": "CTS", "end": "CTS"},
        },
    )
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    mutate_project_manifest(
        tmp_path,
        {
            "type": "register_workspace",
            "workspace_id": "ws_0001",
            "workspace_path": str(workspace),
            "start_step": "Synth",
            "end_step": "Harden",
            "updated_at": "2026-02-01T00:00:00Z",
        },
    )
    mutate_project_manifest(tmp_path, {"type": "archive_workspace", "workspace_id": "ws_0001"})

    assert refresh_workspace_derived_fields(str(tmp_path), "ws_0001") is True

    entry = load_project_manifest(tmp_path)["workspaces"][0]
    assert entry["status"] == "archived"
    assert (entry["start_step"], entry["end_step"]) == ("Synth", "Harden")


def test_select_archived_workspace_as_baseline_and_best(tmp_path):
    workspace = tmp_path / "ws_0001"
    (workspace / "home").mkdir(parents=True)
    (workspace / "home" / "flow.json").write_text(json.dumps({"steps": []}))
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    mutate_project_manifest(
        tmp_path,
        {
            "type": "register_workspace",
            "workspace_id": "ws_0001",
            "workspace_path": str(workspace),
            "updated_at": "2026-02-01T00:00:00Z",
        },
    )
    mutate_project_manifest(tmp_path, {"type": "archive_workspace", "workspace_id": "ws_0001"})

    # An archived entry (e.g. a retained replace backup holding the previous
    # generation's artifacts) is a valid baseline/best target.
    updated = mutate_project_manifest(
        tmp_path,
        {"type": "select_qor_baseline", "workspace_id": "ws_0001", "reason": "Pinned"},
    )
    assert updated["qor_baseline"] == {"workspace_id": "ws_0001", "reason": "Pinned"}
    updated = mutate_project_manifest(
        tmp_path,
        {"type": "select_best_workspace", "workspace_id": "ws_0001", "reason": "Best"},
    )
    assert updated["best_workspace"] == {"workspace_id": "ws_0001", "reason": "Best"}


def test_repoint_generation_pointers_follows_backup_and_keeps_unrelated(tmp_path):
    workspace = tmp_path / "ws_0001"
    other = tmp_path / "ws_0002"
    backup = tmp_path / ".ws_0001.replace-backup-1"
    for directory in (workspace, other, backup):
        (directory / "home").mkdir(parents=True)
        (directory / "home" / "flow.json").write_text(json.dumps({"steps": []}))
    create_project_manifest(tmp_path, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    for workspace_id, directory in (("ws_0001", workspace), ("ws_0002", other)):
        mutate_project_manifest(
            tmp_path,
            {
                "type": "register_workspace",
                "workspace_id": workspace_id,
                "workspace_path": str(directory),
            },
        )
    mutate_project_manifest(
        tmp_path, {"type": "select_qor_baseline", "workspace_id": "ws_0001", "reason": "Pinned"}
    )
    mutate_project_manifest(
        tmp_path, {"type": "select_best_workspace", "workspace_id": "ws_0002", "reason": "Best"}
    )
    register_workspace_backup(tmp_path, backup, source_workspace_id="ws_0001")

    updated = repoint_generation_pointers(tmp_path, "ws_0001", backup.name)

    # The baseline followed the retained backup entry (keeping its reason);
    # the unrelated best pointer is untouched.
    assert updated["qor_baseline"] == {"workspace_id": backup.name, "reason": "Pinned"}
    assert updated["best_workspace"] == {"workspace_id": "ws_0002", "reason": "Best"}

    # Without a registered backup entry the pointer clears instead of
    # dangling at an unregistered id.
    updated = repoint_generation_pointers(tmp_path, "ws_0002", None)
    assert updated["best_workspace"] is None
    assert updated["qor_baseline"] == {"workspace_id": backup.name, "reason": "Pinned"}


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


def test_project_workspace_acquires_workspace_lock_before_manifest_lock(tmp_path, monkeypatch):
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

    assert events == ["workspace:acquire", "manifest:acquire"]
