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

    monkeypatch.setattr(
        "chipcompiler.data.workspace_config._stage_config_bytes", lambda *a, **k: None
    )

    with caplog.at_level("WARNING"):
        loaded = load_workspace(str(workspace_dir))

    assert loaded is not None
    assert loaded.parameters.data["frequency_max"] == 250
    assert loaded.parameters.data["core"]["utilitization"] == 0.55
    # Nothing rewritten; the legacy file stays for the next open to retry.
    assert (workspace_dir / "home" / "parameters.json").is_file()
    assert not (workspace_dir / "home" / "ecc.toml").exists()


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


def test_legacy_null_values_are_dropped_and_migration_completes(
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

    # Null values cannot serialize into TOML, so they are dropped with a
    # warning and the migration completes instead of deferring forever.
    assert loaded is not None
    assert loaded.parameters.data["frequency_max"] == 250
    assert "notes" not in loaded.parameters.data
    assert not legacy_path.exists()


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


def _fail_first_decode(monkeypatch):
    """Make the first candidate verification raise; later calls decode for real."""
    import chipcompiler.data.workspace_config as workspace_config_module

    real_decode = workspace_config_module._decode_workspace_config
    failed = False

    def flaky_decode(path, workspace_dir_arg):
        nonlocal failed
        if not failed:
            failed = True
            raise ValueError("injected verify failure")
        return real_decode(path, workspace_dir_arg)

    monkeypatch.setattr("chipcompiler.data.workspace_config._decode_workspace_config", flaky_decode)


def test_verify_failure_installs_no_toml_and_next_open_retries(
    tmp_path, minimal_ics55_pdk_factory, monkeypatch, caplog
):
    """AC-4: a failed candidate validation installs NO final TOML — the
    legacy JSON is retained and the next open retries the migration
    successfully; retry never depends on cleaning up an installed file."""
    workspace_dir, _pdk_root = _write_legacy_workspace(
        tmp_path, minimal_ics55_pdk_factory, monkeypatch
    )
    config_path = workspace_dir / "home" / "ecc.toml"
    legacy_path = workspace_dir / "home" / "parameters.json"

    _fail_first_decode(monkeypatch)

    with caplog.at_level("WARNING"):
        loaded = load_workspace(str(workspace_dir))

    # Deferred: the in-memory normalized copy serves this open, no final
    # TOML was installed, and the legacy file stays for a retry.
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


def test_verify_failure_with_stubborn_candidate_still_retries(
    tmp_path, minimal_ics55_pdk_factory, monkeypatch, caplog, stubborn_candidate_unlink
):
    """AC-4: a cleanup OSError on the uninstalled candidate must not abort
    the open — the first open still falls back to the normalized copy, and
    the next open retries and installs the TOML."""
    workspace_dir, _pdk_root = _write_legacy_workspace(
        tmp_path, minimal_ics55_pdk_factory, monkeypatch
    )
    config_path = workspace_dir / "home" / "ecc.toml"
    legacy_path = workspace_dir / "home" / "parameters.json"

    _fail_first_decode(monkeypatch)

    with caplog.at_level("WARNING"):
        loaded = load_workspace(str(workspace_dir))

    # The cleanup failure did not abort the open: the normalized in-memory
    # copy serves, no final TOML was installed, the legacy JSON is retained.
    assert loaded is not None
    assert loaded.parameters.data["frequency_max"] == 250
    assert not config_path.exists()
    assert legacy_path.is_file()
    assert any("verify failed" in record.message for record in caplog.records)
    assert any("temporary config candidate" in record.message for record in caplog.records)

    loaded_again = load_workspace(str(workspace_dir))

    assert loaded_again is not None
    assert loaded_again.parameters.data["frequency_max"] == 250
    assert config_path.is_file()
    assert not legacy_path.exists()


def test_load_parameter_reads_legacy_json_when_toml_deferred(tmp_path):
    import json as _json

    home = tmp_path / "home"
    home.mkdir()
    (home / "parameters.json").write_text(_json.dumps({"Design": "gcd", "Max fanout": 48}))

    from chipcompiler.data.parameter import load_parameter

    parameters = load_parameter(home / "parameters.json")

    assert parameters.data == {"design": "gcd", "max_fanout": 48}


def test_non_object_legacy_parameters_open_as_empty(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "parameters.json").write_text("[]")

    from chipcompiler.data import load_workspace
    from chipcompiler.data.workspace_config import legacy_parameters_fallback

    assert legacy_parameters_fallback(tmp_path) == {}
    assert load_workspace(tmp_path) is None
