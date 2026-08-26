#!/usr/bin/env python

import json

import pytest

from chipcompiler.cli.project.manifest import (
    ManifestError,
    assemble_config,
    build_manifest_document,
    classify_project,
    load_manifest,
    resolved_base_parameters,
    update_manifest,
    write_back_workspace_status,
    write_manifest_if_absent,
)


def _write_manifest(project_dir, document):
    path = project_dir / "project.json"
    path.write_text(json.dumps(document))
    return path


def _minimal_document(project_dir, **overrides):
    document = {
        "schema_version": 1,
        "design_name": "gcd",
        "root_path": str(project_dir),
        "workspaces": [],
    }
    document.update(overrides)
    return document


def test_load_manifest_tolerant_defaults(tmp_path):
    _write_manifest(tmp_path, _minimal_document(tmp_path))

    manifest = load_manifest(str(tmp_path))

    assert manifest.design_name == "gcd"
    assert manifest.name == tmp_path.name
    assert manifest.project_id.startswith("proj_")
    assert manifest.objectives["primary"] == "timing"
    # The GUI parser keeps only maximize/minimize entries from the source.
    assert manifest.objectives["directions"] == {}
    assert manifest.base_design["parameters"] == {}
    assert manifest.qor_baseline is None
    assert manifest.workspaces == ()


def test_load_manifest_normalizes_workspace_entries(tmp_path):
    workspace_dir = tmp_path / "ws_0001"
    _write_manifest(
        tmp_path,
        _minimal_document(
            tmp_path,
            workspaces=[
                {
                    "workspace_id": "ws_0001",
                    "workspace_path": str(workspace_dir),
                    "status": "bogus",
                }
            ],
        ),
    )

    manifest = load_manifest(str(tmp_path))

    (entry,) = manifest.workspaces
    assert entry.workspace_id == "ws_0001"
    assert entry.workspace_path == str(workspace_dir)
    assert entry.start_step == "Synth"
    assert entry.end_step == "Harden"
    assert entry.status == "not_started"
    assert manifest.active_workspaces() == [entry]


def test_load_manifest_relative_workspace_path_resolves_inside_root(tmp_path):
    _write_manifest(
        tmp_path,
        _minimal_document(
            tmp_path,
            workspaces=[{"workspace_id": "run1", "workspace_path": "run1"}],
        ),
    )

    manifest = load_manifest(str(tmp_path))
    assert manifest.workspaces[0].workspace_path == str(tmp_path / "run1")


def test_load_manifest_rejects_parse_failure(tmp_path):
    (tmp_path / "project.json").write_text("{not json")
    with pytest.raises(ManifestError):
        load_manifest(str(tmp_path))


def test_load_manifest_rejects_schema_mismatch_and_missing_workspaces(tmp_path):
    _write_manifest(tmp_path, _minimal_document(tmp_path, schema_version=2))
    with pytest.raises(ManifestError):
        load_manifest(str(tmp_path))

    document = _minimal_document(tmp_path)
    del document["workspaces"]
    _write_manifest(tmp_path, document)
    with pytest.raises(ManifestError):
        load_manifest(str(tmp_path))


def test_load_manifest_rejects_root_path_mismatch(tmp_path):
    _write_manifest(tmp_path, _minimal_document(tmp_path, root_path="/somewhere/else"))
    with pytest.raises(ManifestError):
        load_manifest(str(tmp_path))


def test_load_manifest_rejects_workspace_outside_root(tmp_path):
    _write_manifest(
        tmp_path,
        _minimal_document(
            tmp_path,
            workspaces=[{"workspace_id": "ws", "workspace_path": str(tmp_path.parent / "x")}],
        ),
    )
    with pytest.raises(ManifestError):
        load_manifest(str(tmp_path))


def test_find_workspace_matches_id_and_path_tail(tmp_path):
    _write_manifest(
        tmp_path,
        _minimal_document(
            tmp_path,
            workspaces=[
                {
                    "workspace_id": "ws_0001",
                    "workspace_path": str(tmp_path / "custom_dir"),
                }
            ],
        ),
    )
    manifest = load_manifest(str(tmp_path))

    assert manifest.find_workspace("ws_0001") is manifest.workspaces[0]
    assert manifest.find_workspace("custom_dir") is manifest.workspaces[0]
    assert manifest.find_workspace("nope") is None


def test_assemble_config_layers_base_design_and_parameter_patch(tmp_path):
    _write_manifest(
        tmp_path,
        _minimal_document(
            tmp_path,
            base_design={
                "pdk": "ics55",
                "pdk_root": "/pdk",
                "top_module": "gcd",
                "clock": "clk",
                "rtl_list": ["rtl/gcd.v"],
                "parameters": {"frequency_max": 100, "max_fanout": 20},
            },
            workspaces=[
                {
                    "workspace_id": "ws_0001",
                    "workspace_path": str(tmp_path / "ws_0001"),
                    "parameter_patch": {"frequency_max": {"from": 100, "to": 200}},
                }
            ],
        ),
    )
    manifest = load_manifest(str(tmp_path))

    assembled = assemble_config(manifest, manifest.workspaces[0])

    assert assembled["pdk"] == "ics55"
    assert assembled["pdk_root"] == "/pdk"
    assert assembled["design_name"] == "gcd"
    assert assembled["top_module"] == "gcd"
    assert assembled["clock"] == "clk"
    assert assembled["rtl_list"] == ["rtl/gcd.v"]
    assert assembled["parameters"]["frequency_max"] == 200
    assert assembled["parameters"]["max_fanout"] == 20


def test_classify_project(tmp_path):
    assert classify_project(str(tmp_path)) == "virgin"

    (tmp_path / "runs" / "default").mkdir(parents=True)
    assert classify_project(str(tmp_path)) == "legacy"

    (tmp_path / "project.json").write_text("{}")
    assert classify_project(str(tmp_path)) == "manifest"


def test_write_manifest_if_absent_wins_and_loses_race(tmp_path):
    document = build_manifest_document(
        str(tmp_path),
        design_name="gcd",
        base_design={"pdk": "ics55", "parameters": {"design": "gcd"}},
        workspace_id="default",
        workspace_path=str(tmp_path / "default"),
        start_step="Synth",
        end_step="Filler",
    )
    assert write_manifest_if_absent(str(tmp_path), document) is True
    assert write_manifest_if_absent(str(tmp_path), document) is False

    written = json.loads((tmp_path / "project.json").read_text())
    assert written["schema_version"] == 1
    assert written["design_name"] == "gcd"
    assert written["root_path"] == str(tmp_path)
    assert written["qor_baseline"]["workspace_id"] == "default"
    (entry,) = written["workspaces"]
    assert entry["workspace_id"] == "default"
    assert entry["start_step"] == "Synth"
    assert entry["end_step"] == "Filler"
    assert entry["status"] == "running"


def test_update_manifest_preserves_unrelated_fields(tmp_path):
    document = build_manifest_document(
        str(tmp_path),
        design_name="gcd",
        base_design={"parameters": {"design": "gcd"}},
        workspace_id="default",
        workspace_path=str(tmp_path / "default"),
        start_step="Synth",
        end_step="Filler",
    )
    write_manifest_if_absent(str(tmp_path), document)

    def mutate(doc):
        doc["workspaces"][0]["status"] = "success"
        doc["custom_gui_field"] = {"kept": True}

    assert update_manifest(str(tmp_path), mutate) is True

    written = json.loads((tmp_path / "project.json").read_text())
    assert written["workspaces"][0]["status"] == "success"
    assert written["custom_gui_field"] == {"kept": True}


def test_update_manifest_missing_file_returns_false(tmp_path):
    assert update_manifest(str(tmp_path), lambda doc: None) is False


def test_write_back_workspace_status(tmp_path):
    document = build_manifest_document(
        str(tmp_path),
        design_name="gcd",
        base_design={"parameters": {"design": "gcd"}},
        workspace_id="default",
        workspace_path=str(tmp_path / "default"),
        start_step="Synth",
        end_step="Filler",
    )
    write_manifest_if_absent(str(tmp_path), document)

    assert write_back_workspace_status(str(tmp_path), "default", "failed") is True
    written = json.loads((tmp_path / "project.json").read_text())
    assert written["workspaces"][0]["status"] == "failed"

    # Unknown workspace ids degrade to a no-op, not an error.
    assert write_back_workspace_status(str(tmp_path), "unknown", "failed") is True


def test_load_manifest_rejects_malformed_mpc(tmp_path):
    _write_manifest(tmp_path, _minimal_document(tmp_path, mpc={"resource_id": "bogus"}))
    with pytest.raises(ManifestError):
        load_manifest(str(tmp_path))


def test_load_manifest_accepts_null_mpc(tmp_path):
    _write_manifest(tmp_path, _minimal_document(tmp_path, mpc=None))
    assert load_manifest(str(tmp_path)).design_name == "gcd"


def test_resolved_base_parameters_gui_flat_vocabulary():
    from chipcompiler.cli.project.config import ProjectConfig

    cfg = ProjectConfig(
        design_name="gcd",
        design_top="gcd",
        design_clock_port="clk",
        design_frequency_mhz=200.0,
        params_overrides={"floorplan.core_util": 0.45, "synth.max_fanout": 16},
    )

    parameters = resolved_base_parameters(cfg)

    assert parameters["design"] == "gcd"
    assert parameters["top_module"] == "gcd"
    assert parameters["clock"] == "clk"
    assert parameters["frequency_max"] == 200.0
    # Positional overrides surface as GUI aliases, not nested subtrees.
    assert parameters["utilitization"] == 0.45
    assert parameters["max_fanout"] == 16
    # Exclusive GUI-flat shape: no canonical geometry subtrees survive.
    assert "die" not in parameters
    assert "core" not in parameters


def test_update_manifest_preserves_interleaved_unrelated_change(tmp_path):
    document = build_manifest_document(
        str(tmp_path),
        design_name="gcd",
        base_design={"parameters": {"design": "gcd"}},
        workspace_id="default",
        workspace_path=str(tmp_path / "default"),
        start_step="Synth",
        end_step="Filler",
    )
    write_manifest_if_absent(str(tmp_path), document)

    def mutate(doc):
        # A concurrent writer lands an unrelated edit mid-update.
        fresh = json.loads((tmp_path / "project.json").read_text())
        fresh["custom_gui_field"] = {"concurrent": True}
        (tmp_path / "project.json").write_text(json.dumps(fresh))
        doc["workspaces"][0]["status"] = "failed"

    assert update_manifest(str(tmp_path), mutate) is True

    written = json.loads((tmp_path / "project.json").read_text())
    # Both our status change and the interleaved GUI edit survive.
    assert written["workspaces"][0]["status"] == "failed"
    assert written["custom_gui_field"] == {"concurrent": True}


def test_status_write_back_touches_only_target_entry(tmp_path):
    document = build_manifest_document(
        str(tmp_path),
        design_name="gcd",
        base_design={"parameters": {"design": "gcd"}},
        workspace_id="default",
        workspace_path=str(tmp_path / "default"),
        start_step="Synth",
        end_step="Filler",
    )
    write_manifest_if_absent(str(tmp_path), document)
    before = json.loads((tmp_path / "project.json").read_text())

    assert write_back_workspace_status(str(tmp_path), "default", "success") is True

    after = json.loads((tmp_path / "project.json").read_text())
    changed = []
    for key in after:
        if after[key] != before[key]:
            changed.append(key)
    # Only the workspaces array changes, and within it only status/updated_at.
    assert changed == ["workspaces"]
    entry_before, entry_after = before["workspaces"][0], after["workspaces"][0]
    changed_entry_keys = [k for k in entry_after if entry_after[k] != entry_before.get(k)]
    assert sorted(changed_entry_keys) == ["status", "updated_at"]
    assert entry_after["status"] == "success"


def test_resolved_base_parameters_whole_object():
    from chipcompiler.cli.project.config import ProjectConfig

    cfg = ProjectConfig(
        design_name="gcd",
        design_top="gcd",
        design_clock_port="clk",
        design_frequency_mhz=200.0,
        params_overrides={"floorplan.core_util": 0.45, "floorplan.core_margin": [3, 3]},
    )

    assert resolved_base_parameters(cfg) == {
        "design": "gcd",
        "top_module": "gcd",
        "clock": "clk",
        "frequency_max": 200.0,
        "utilitization": 0.45,
        "margin": 3,
        "die_area_mode": "utilitization_margin",
    }


def test_load_manifest_tolerates_wrong_field_types(tmp_path):
    _write_manifest(
        tmp_path,
        _minimal_document(
            tmp_path,
            workspaces=[
                {
                    "workspace_id": "ws_0001",
                    "workspace_path": str(tmp_path / "ws_0001"),
                    "status": [],
                }
            ],
        ),
    )

    manifest = load_manifest(str(tmp_path))

    (entry,) = manifest.workspaces
    assert entry.status == "not_started"


def test_assemble_config_tolerates_non_list_rtl(tmp_path):
    _write_manifest(
        tmp_path,
        _minimal_document(tmp_path, base_design={"pdk": "ics55", "rtl_list": 1}),
    )

    manifest = load_manifest(str(tmp_path))
    assembled = assemble_config(manifest, None)

    assert assembled["rtl_list"] == []


def test_load_manifest_rejects_boolean_schema_version(tmp_path):
    # True == 1 in Python, but a JSON boolean is not the schema version —
    # the GUI parser rejects it and the CLI must not open what the GUI
    # cannot.
    _write_manifest(tmp_path, _minimal_document(tmp_path, schema_version=True))

    with pytest.raises(ManifestError, match="schema_version 1 is required"):
        load_manifest(str(tmp_path))


def test_load_manifest_rejects_boolean_mpc_design_index(tmp_path):
    _write_manifest(
        tmp_path,
        _minimal_document(
            tmp_path,
            mpc={
                "resource_id": "mpc:x",
                "display_name": "d",
                "installed_version": "1",
                "path": "/p",
                "spec_path": "/p/spec/spec.json.in",
                "design": {"index": True, "design_name": "gcd"},
                "core_template": {},
            },
        ),
    )

    with pytest.raises(ManifestError, match="mpc.design"):
        load_manifest(str(tmp_path))


def test_load_manifest_accepts_integral_float_mpc_design_index(tmp_path):
    # The GUI parser uses Number.isInteger: JSON 0.0 is a valid index.
    _write_manifest(
        tmp_path,
        _minimal_document(
            tmp_path,
            mpc={
                "resource_id": "mpc:x",
                "display_name": "d",
                "installed_version": "1",
                "path": "/p",
                "spec_path": "/p/spec/spec.json.in",
                "design": {"index": 0.0, "design_name": "gcd"},
                "core_template": {},
            },
        ),
    )

    manifest = load_manifest(str(tmp_path))

    assert manifest.design_name == "gcd"


def test_load_manifest_rejects_fractional_mpc_design_index(tmp_path):
    _write_manifest(
        tmp_path,
        _minimal_document(
            tmp_path,
            mpc={
                "resource_id": "mpc:x",
                "display_name": "d",
                "installed_version": "1",
                "path": "/p",
                "spec_path": "/p/spec/spec.json.in",
                "design": {"index": 2.5, "design_name": "gcd"},
                "core_template": {},
            },
        ),
    )

    with pytest.raises(ManifestError, match="mpc.design"):
        load_manifest(str(tmp_path))


def test_load_manifest_tolerates_huge_integer_mpc_design_index(tmp_path):
    # float(10**400) raises OverflowError; ints are integral by
    # construction, so the check never float-converts them.
    _write_manifest(
        tmp_path,
        _minimal_document(
            tmp_path,
            mpc={
                "resource_id": "mpc:x",
                "display_name": "d",
                "installed_version": "1",
                "path": "/p",
                "spec_path": "/p/spec/spec.json.in",
                "design": {"index": 10**400, "design_name": "gcd"},
                "core_template": {},
            },
        ),
    )

    manifest = load_manifest(str(tmp_path))

    assert manifest.design_name == "gcd"


def test_update_manifest_degrades_when_lock_is_unopenable(tmp_path):
    _write_manifest(tmp_path, _minimal_document(tmp_path))
    # A directory at the lock path: flock cannot be taken — degrade to
    # False (callers warn/roll back), never an uncaught OSError.
    (tmp_path / ".manifest.lock").mkdir()

    assert update_manifest(str(tmp_path), lambda document: None) is False


def test_load_manifest_stores_canonical_workspace_path_through_symlink(tmp_path):
    real_dir = tmp_path / "proj" / "ws_0001"
    real_dir.mkdir(parents=True)
    (tmp_path / "proj" / "linked").symlink_to(real_dir)
    document = {
        "schema_version": 1,
        "root_path": str(tmp_path / "proj"),
        "design_name": "gcd",
        "workspaces": [
            {"workspace_id": "ws_0001", "workspace_path": str(tmp_path / "proj" / "linked")}
        ],
    }
    import json

    (tmp_path / "proj" / "project.json").write_text(json.dumps(document))

    manifest = load_manifest(str(tmp_path / "proj"))

    assert manifest.workspaces[0].workspace_path == str(real_dir.resolve())


def test_load_manifest_symlink_loop_is_a_manifest_error_not_a_traceback(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    loop = project_dir / "ws_0001"
    loop.symlink_to(loop)
    document = {
        "schema_version": 1,
        "root_path": str(project_dir),
        "design_name": "gcd",
        "workspaces": [{"workspace_id": "ws_0001", "workspace_path": str(loop)}],
    }
    import json

    (project_dir / "project.json").write_text(json.dumps(document))

    with pytest.raises(ManifestError, match="cannot be resolved"):
        load_manifest(str(project_dir))
