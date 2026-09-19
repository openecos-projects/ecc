#!/usr/bin/env python

"""The derived-config manifest: refresh_workspace_config records the hashes
of the generated config/*.json, and modified_derived_configs reports drift
since the last derivation."""

import json

from chipcompiler.data.workspace.config_manifest import (
    DERIVED_CONFIG_MANIFEST_FILENAME,
    derived_config_manifest_path,
    modified_derived_configs,
)


def _create_workspace(tmp_path, minimal_ics55_pdk_factory):
    from chipcompiler.data import create_workspace

    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    workspace_dir = tmp_path / "workspace"
    created = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters={"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
        pdk_root=str(pdk_root),
    )
    assert created is not None
    return workspace_dir


def test_creation_records_the_derived_state(tmp_path, minimal_ics55_pdk_factory):
    workspace_dir = _create_workspace(tmp_path, minimal_ics55_pdk_factory)

    manifest_path = derived_config_manifest_path(workspace_dir)
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text())
    # The managed generated configs are all recorded, with real digests.
    assert "db_ecc.json" in manifest["files"]
    assert "cts_ecc.json" in manifest["files"]
    assert all(len(entry["sha256"]) == 64 for entry in manifest["files"].values())
    assert modified_derived_configs(workspace_dir) == []


def test_hand_edit_is_reported(tmp_path, minimal_ics55_pdk_factory):
    workspace_dir = _create_workspace(tmp_path, minimal_ics55_pdk_factory)

    cts_path = workspace_dir / "config" / "cts_ecc.json"
    cts = json.loads(cts_path.read_text())
    cts["max_fanout"] = 7
    cts_path.write_text(json.dumps(cts))

    assert modified_derived_configs(workspace_dir) == ["cts_ecc.json"]


def test_missing_record_or_missing_file(tmp_path, minimal_ics55_pdk_factory):
    from chipcompiler.data import load_workspace, refresh_workspace_config

    workspace_dir = _create_workspace(tmp_path, minimal_ics55_pdk_factory)

    # No record (first refresh / pre-record workspace): nothing to compare.
    derived_config_manifest_path(workspace_dir).unlink()
    assert modified_derived_configs(workspace_dir) == []

    # Re-derive to get a fresh record: a file deleted since the derivation
    # counts as modified.
    workspace = load_workspace(str(workspace_dir))
    assert workspace is not None
    refresh_workspace_config(workspace)
    assert modified_derived_configs(workspace_dir) == []
    (workspace_dir / "config" / "db_ecc.json").unlink()
    assert modified_derived_configs(workspace_dir) == ["db_ecc.json"]


def test_rerun_derivation_clears_the_drift(tmp_path, minimal_ics55_pdk_factory):
    from chipcompiler.data import load_workspace, refresh_workspace_config

    workspace_dir = _create_workspace(tmp_path, minimal_ics55_pdk_factory)
    cts_path = workspace_dir / "config" / "cts_ecc.json"
    cts = json.loads(cts_path.read_text())
    cts["max_fanout"] = 7
    cts_path.write_text(json.dumps(cts))
    assert modified_derived_configs(workspace_dir) == ["cts_ecc.json"]

    workspace = load_workspace(str(workspace_dir))
    assert workspace is not None
    refresh_workspace_config(workspace)

    assert modified_derived_configs(workspace_dir) == []
    manifest_path = derived_config_manifest_path(workspace_dir)
    assert manifest_path.name == DERIVED_CONFIG_MANIFEST_FILENAME
