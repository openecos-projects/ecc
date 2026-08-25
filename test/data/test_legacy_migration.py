#!/usr/bin/env python

import json
from pathlib import Path

import pytest

from chipcompiler.data import create_workspace, load_workspace
from chipcompiler.data.parameter import (
    ICS55_PARAMETERS_TEMPLATE,
    SG13G2_PARAMETERS_TEMPLATE,
    load_parameter,
)
from chipcompiler.data.parameter_keys import normalize_key

LEGACY_LONG_KEYS = (
    "PDK",
    "Design",
    "Top module",
    "Clock",
    "Frequency max [MHz]",
    "Max fanout",
    "Target density",
    "Target overflow",
    "Bottom layer",
    "Top layer",
    "STA max paths",
    "Cell padding x",
    "Global right padding",
    "Routability opt flag",
    "Die",
    "Core",
    "Floorplan",
    "PDN",
    "DreamPlace",
)


def _walk_keys(data):
    if isinstance(data, dict):
        for key, value in data.items():
            yield key
            yield from _walk_keys(value)
    elif isinstance(data, list):
        for item in data:
            yield from _walk_keys(item)


def test_templates_contain_only_canonical_keys():
    for template in (ICS55_PARAMETERS_TEMPLATE, SG13G2_PARAMETERS_TEMPLATE):
        keys = set(_walk_keys(template))
        assert keys.isdisjoint(LEGACY_LONG_KEYS)
        for key in keys:
            assert key == normalize_key(key)


def test_loaded_parameters_contain_only_canonical_keys(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters=default_ics55_parameters,
        pdk_root=str(pdk_root),
    )

    for source in (
        load_workspace(str(workspace_dir)).parameters.data,
        load_parameter(workspace_dir / "home" / "ecc.toml").data,
    ):
        keys = set(_walk_keys(source))
        assert keys.isdisjoint(LEGACY_LONG_KEYS)


def _write_legacy_workspace(tmp_path, minimal_ics55_pdk_factory, monkeypatch):
    """Create a workspace, then downgrade its config to the legacy JSON form."""
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters={"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
        pdk_root=str(pdk_root),
    )
    # Downgrade: long-key parameters.json replaces the TOML config.
    legacy = {
        "PDK": "ics55",
        "Design": "gcd",
        "Top module": "gcd",
        "Clock": "clk",
        "Frequency max [MHz]": 250,
        "PDK Root": str(pdk_root.resolve()),
        "Core": {"Utilitization": 0.55, "Margin": [3, 3]},
    }
    (workspace_dir / "home" / "ecc.toml").unlink()
    (workspace_dir / "home" / "parameters.json").write_text(json.dumps(legacy))
    return workspace_dir, pdk_root


def test_legacy_parameters_migrate_on_open(tmp_path, minimal_ics55_pdk_factory, monkeypatch):
    workspace_dir, pdk_root = _write_legacy_workspace(
        tmp_path, minimal_ics55_pdk_factory, monkeypatch
    )

    loaded = load_workspace(str(workspace_dir))

    assert loaded is not None
    config_path = workspace_dir / "home" / "ecc.toml"
    assert config_path.is_file()
    assert not (workspace_dir / "home" / "parameters.json").exists()
    assert loaded.parameters.data["frequency_max"] == 250
    assert loaded.parameters.data["core"]["utilitization"] == 0.55
    assert loaded.parameters.data["pdk_root"] == str(pdk_root.resolve())
    home_data = json.loads((workspace_dir / "home" / "home.json").read_text())
    assert home_data["parameters"] == str(config_path)


def test_both_files_present_toml_wins_json_untouched(
    tmp_path, minimal_ics55_pdk_factory, monkeypatch, caplog
):
    workspace_dir, pdk_root = _write_legacy_workspace(
        tmp_path, minimal_ics55_pdk_factory, monkeypatch
    )
    # Recreate the TOML alongside the legacy JSON: TOML must win.
    loaded_once = load_workspace(str(workspace_dir))
    assert loaded_once is not None
    legacy_path = workspace_dir / "home" / "parameters.json"
    legacy_path.write_text(json.dumps({"Design": "stale"}))

    with caplog.at_level("WARNING"):
        loaded = load_workspace(str(workspace_dir))

    assert loaded is not None
    assert loaded.parameters.data["design"] == "gcd"
    assert legacy_path.is_file()
    assert json.loads(legacy_path.read_text()) == {"Design": "stale"}
    assert any("workspace_config_shadowed" in record.message for record in caplog.records)


def test_rewrite_failure_falls_back_to_in_memory_copy(
    tmp_path, minimal_ics55_pdk_factory, monkeypatch, caplog
):
    workspace_dir, _pdk_root = _write_legacy_workspace(
        tmp_path, minimal_ics55_pdk_factory, monkeypatch
    )

    import chipcompiler.data.workspace as workspace_module

    monkeypatch.setattr(
        "chipcompiler.data.workspace_config.save_workspace_config", lambda *a, **k: False
    )

    with caplog.at_level("WARNING"):
        loaded = load_workspace(str(workspace_dir))

    assert loaded is not None
    assert loaded.parameters.data["frequency_max"] == 250
    assert loaded.parameters.data["core"]["utilitization"] == 0.55
    # Nothing rewritten; the legacy file stays for the next open to retry.
    assert (workspace_dir / "home" / "parameters.json").is_file()
    assert not (workspace_dir / "home" / "ecc.toml").exists()
    assert workspace_module is not None  # silence unused import lint


def test_malformed_toml_never_falls_back_to_legacy_json(
    tmp_path, minimal_ics55_pdk_factory, monkeypatch
):
    workspace_dir, _pdk_root = _write_legacy_workspace(
        tmp_path, minimal_ics55_pdk_factory, monkeypatch
    )
    # Both files present, TOML malformed: the workspace must not silently
    # load the stale JSON values — the invalid config surfaces loudly.
    (workspace_dir / "home" / "ecc.toml").write_text("[params\nbroken =")

    from chipcompiler.data.workspace_config import WorkspaceConfigError

    with pytest.raises(WorkspaceConfigError):
        load_workspace(str(workspace_dir))


def test_legacy_null_values_do_not_abort_migration(
    tmp_path, minimal_ics55_pdk_factory, monkeypatch
):
    workspace_dir, _pdk_root = _write_legacy_workspace(
        tmp_path, minimal_ics55_pdk_factory, monkeypatch
    )
    legacy_path = workspace_dir / "home" / "parameters.json"
    legacy = json.loads(legacy_path.read_text())
    legacy["notes"] = None
    legacy_path.write_text(json.dumps(legacy))

    loaded = load_workspace(str(workspace_dir))

    # The rewrite cannot serialize null; the workspace still opens from the
    # normalized in-memory copy and the legacy file stays for a later retry.
    assert loaded is not None
    assert loaded.parameters.data["frequency_max"] == 250
    assert legacy_path.is_file()


def test_create_workspace_seeds_flow_range_from_flow_config(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    workspace_dir = tmp_path / "workspace"

    create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters={"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
        pdk_root=str(pdk_root),
        flow_config={"start_step": "Place", "end_step": "Route"},
    )

    loaded = load_workspace(str(workspace_dir))
    assert loaded is not None
    assert loaded.parameters.data["_flow"] == {"start": "place", "end": "route"}


def test_migration_seeds_flow_section_from_persisted_flow(
    tmp_path, minimal_ics55_pdk_factory, monkeypatch
):
    workspace_dir, _pdk_root = _write_legacy_workspace(
        tmp_path, minimal_ics55_pdk_factory, monkeypatch
    )
    steps = {
        "steps": [
            {"name": "Synthesis", "tool": "yosys", "state": "Success"},
            {"name": "Floorplan", "tool": "ecc", "state": "Success"},
        ]
    }
    (workspace_dir / "home" / "flow.json").write_text(json.dumps(steps))

    loaded = load_workspace(str(workspace_dir))

    assert loaded is not None
    assert loaded.parameters.data["_flow"] == {"start": "Synthesis", "end": "Floorplan"}


def test_verify_failure_removes_new_toml_and_next_open_retries(
    tmp_path, minimal_ics55_pdk_factory, monkeypatch, caplog
):
    """AC-4: a failed post-write verification removes only the TOML that
    invocation created — the legacy JSON is retained and the next open
    retries the migration successfully."""
    workspace_dir, _pdk_root = _write_legacy_workspace(
        tmp_path, minimal_ics55_pdk_factory, monkeypatch
    )
    config_path = workspace_dir / "home" / "ecc.toml"
    legacy_path = workspace_dir / "home" / "parameters.json"

    import chipcompiler.data.workspace_config as workspace_config_module

    real_load = workspace_config_module.load_workspace_config
    calls = {"n": 0}

    def flaky_load(workspace_dir_arg):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("injected verify failure")
        return real_load(workspace_dir_arg)

    monkeypatch.setattr("chipcompiler.data.workspace_config.load_workspace_config", flaky_load)

    with caplog.at_level("WARNING"):
        loaded = load_workspace(str(workspace_dir))

    # Deferred: the in-memory normalized copy serves this open, the
    # invocation-created TOML is gone, and the legacy file stays for a retry.
    assert loaded is not None
    assert loaded.parameters.data["frequency_max"] == 250
    assert not config_path.exists()
    assert legacy_path.is_file()
    assert any("verify failed" in record.message for record in caplog.records)

    loaded_again = load_workspace(str(workspace_dir))

    assert loaded_again is not None
    assert loaded_again.parameters.data["frequency_max"] == 250
    assert loaded_again.parameters.data["core"]["utilitization"] == 0.55
    assert config_path.is_file()
    assert not legacy_path.exists()


def test_legacy_unlink_failure_still_opens_verified_toml(
    tmp_path, minimal_ics55_pdk_factory, monkeypatch, caplog
):
    """AC-4: a cleanup failure after a verified rewrite warns but does not
    abort the open; the verified TOML wins on later opens too."""
    workspace_dir, _pdk_root = _write_legacy_workspace(
        tmp_path, minimal_ics55_pdk_factory, monkeypatch
    )
    config_path = workspace_dir / "home" / "ecc.toml"
    legacy_path = workspace_dir / "home" / "parameters.json"

    real_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        if self == legacy_path:
            raise OSError("injected unlink failure")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    with caplog.at_level("WARNING"):
        loaded = load_workspace(str(workspace_dir))

    assert loaded is not None
    assert loaded.parameters.data["frequency_max"] == 250
    assert config_path.is_file()
    assert legacy_path.is_file()
    assert any("could not be removed" in record.message for record in caplog.records)

    # Both files now present: the TOML-wins shadow branch serves later opens.
    loaded_again = load_workspace(str(workspace_dir))
    assert loaded_again is not None
    assert loaded_again.parameters.data["frequency_max"] == 250
