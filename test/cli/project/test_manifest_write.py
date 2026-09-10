#!/usr/bin/env python

import json

from chipcompiler.cli.project.manifest_write import (
    build_manifest_document,
    pre_register_workspace,
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


def test_pre_register_workspace_writes_a_manifest_entry_before_workspace_creation(tmp_path):
    from chipcompiler.cli.project.config import ProjectConfig

    cfg = ProjectConfig(
        design_name="gcd",
        design_top="gcd",
        design_clock_port="clk",
        design_frequency_mhz=100.0,
        design_netlist="input/gcd.v",
        design_def="input/gcd.def",
        pdk_name="ics55",
        flow_preset="rtl2gds",
        project_dir=str(tmp_path),
    )

    result = pre_register_workspace(
        str(tmp_path),
        cfg=cfg,
        pdk_root="/pdk",
        workspace_id="cts-only",
        workspace_path=str(tmp_path / "cts-only"),
        flow_config={"start_step": "CTS", "end_step": "CTS"},
    )

    assert result == "registered"
    assert not (tmp_path / "cts-only").exists()
    document = json.loads((tmp_path / "project.json").read_text())
    entry = document["workspaces"][0]
    assert entry["workspace_id"] == "cts-only"
    assert entry["start_step"] == "CTS"
    assert entry["end_step"] == "CTS"
    assert entry["status"] == "not_started"
    assert "input_snapshot" not in entry


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


def test_update_manifest_degrades_when_lock_is_unopenable(tmp_path):
    _write_manifest(tmp_path, _minimal_document(tmp_path))
    # A directory at the lock path: flock cannot be taken — degrade to
    # False (callers warn/roll back), never an uncaught OSError.
    (tmp_path / ".manifest.lock").mkdir()

    assert update_manifest(str(tmp_path), lambda document: None) is False
