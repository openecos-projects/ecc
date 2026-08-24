#!/usr/bin/env python

import json

import pytest

from chipcompiler.cli.project.manifest import (
    DEFAULT_OBJECTIVES,
    ManifestError,
    assemble_config,
    build_manifest_document,
    classify_project,
    load_manifest,
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
    assert manifest.objectives["directions"] == DEFAULT_OBJECTIVES["directions"]
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
