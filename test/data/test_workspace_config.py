#!/usr/bin/env python

import pytest

from chipcompiler.data.parameter import (
    ICS55_PARAMETERS_TEMPLATE,
    SG13G2_PARAMETERS_TEMPLATE,
)
from chipcompiler.data.parameter_keys import normalize_keys
from chipcompiler.data.workspace_config import (
    WorkspaceConfigError,
    WorkspaceFlowTargetError,
    canonical_flow_chain,
    flow_range_for_preset,
    flow_range_of,
    flow_section_from_flow_config,
    flow_steps_in_range,
    load_workspace_config,
    parameters_have_chip_identity,
    save_workspace_config,
    validate_flow_config,
    workspace_config_path,
)


def _flat_template(template: dict) -> dict:
    flat = normalize_keys(template)
    assert isinstance(flat, dict)
    return flat


def test_save_load_round_trip_ics55(tmp_path):
    payload = _flat_template(ICS55_PARAMETERS_TEMPLATE)
    payload.update(
        {
            "design": "gcd",
            "top_module": "gcd",
            "clock": "clk",
            "pdk_root": "/abs/pdk",
            "pdk_config": str(tmp_path / "home" / "pdk.json"),
        }
    )
    assert save_workspace_config(tmp_path, payload, {"preset": "rtl2gds"})

    loaded = load_workspace_config(tmp_path)
    params = {key: value for key, value in loaded.items() if key != "_flow"}
    assert params == payload
    assert loaded["_flow"] == {"preset": "rtl2gds"}


def test_save_load_round_trip_sg13g2_nested_subtrees(tmp_path):
    payload = _flat_template(SG13G2_PARAMETERS_TEMPLATE)
    assert save_workspace_config(tmp_path, payload)

    loaded = load_workspace_config(tmp_path)
    params = {key: value for key, value in loaded.items() if key != "_flow"}
    assert params == payload
    assert loaded["_flow"] == {}


def test_save_load_round_trip_preserves_reserved_payloads(tmp_path):
    payload = {
        "design": "gcd",
        "config_overrides": {
            "route": {"RT": {"-thread_number": "16"}},
            "dreamplace": {
                "RePlAce_LOWER_PCOF": 1.2,
                "global_place_stages": [{"Llambda_density_weight_iteration": 2}],
            },
            "sta": {"signoff": [{"MAX": ["Cworst"], "MIN": ["Cbest"]}]},
        },
        "workspace_param_overrides": [
            {"key": "route.RT.-thread_number", "baseline": "50", "value": "16"}
        ],
    }
    assert save_workspace_config(tmp_path, payload)

    loaded = load_workspace_config(tmp_path)
    assert loaded["config_overrides"] == payload["config_overrides"]
    assert loaded["workspace_param_overrides"] == payload["workspace_param_overrides"]


def test_design_section_mirrors_identity_keys(tmp_path):
    payload = _flat_template(ICS55_PARAMETERS_TEMPLATE)
    payload.update({"design": "gcd", "top_module": "gcd", "clock": "clk"})
    save_workspace_config(tmp_path, payload)

    text = workspace_config_path(tmp_path).read_text()
    assert "[design]" in text
    assert 'name = "gcd"' in text
    assert 'top = "gcd"' in text
    assert 'clock_port = "clk"' in text


def test_workspace_relative_pdk_config_resolves_on_load(tmp_path):
    payload = _flat_template(ICS55_PARAMETERS_TEMPLATE)
    absolute_config = str(tmp_path / "home" / "pdk.json")
    payload["pdk_config"] = absolute_config
    save_workspace_config(tmp_path, payload)

    text = workspace_config_path(tmp_path).read_text()
    assert 'config = "home/pdk.json"' in text

    loaded = load_workspace_config(tmp_path)
    assert loaded["pdk_config"] == absolute_config


def test_absolute_pdk_config_outside_workspace_stays_absolute(tmp_path):
    payload = _flat_template(ICS55_PARAMETERS_TEMPLATE)
    payload["pdk_config"] = "/elsewhere/pdk.json"
    save_workspace_config(tmp_path, payload)
    loaded = load_workspace_config(tmp_path)
    assert loaded["pdk_config"] == "/elsewhere/pdk.json"


def test_flow_validation_preset_with_start_end_rejected():
    with pytest.raises(WorkspaceFlowTargetError):
        validate_flow_config({"preset": "rtl2gds", "start": "Synthesis", "end": "Harden"})


def test_flow_validation_single_start_rejected():
    with pytest.raises(WorkspaceFlowTargetError):
        validate_flow_config({"start": "Synthesis"})
    with pytest.raises(WorkspaceFlowTargetError):
        validate_flow_config({"end": "Harden"})


def test_flow_validation_unknown_step_rejected():
    with pytest.raises(WorkspaceFlowTargetError):
        validate_flow_config({"start": "Synthesis", "end": "not_a_step"})


def test_flow_validation_start_after_end_rejected():
    with pytest.raises(WorkspaceFlowTargetError):
        validate_flow_config({"start": "Harden", "end": "Synthesis"})


def test_flow_validation_accepts_canonical_names():
    assert validate_flow_config({"start": "Synthesis", "end": "filler"}) == {
        "start": "Synthesis",
        "end": "filler",
    }


def test_flow_validation_rejects_display_name_aliases():
    # Workspace files carry canonical names only; aliases translate at the
    # manifest/RPC boundary.
    with pytest.raises(WorkspaceFlowTargetError):
        validate_flow_config({"start": "Synth", "end": "Filler"})


def test_save_rejects_invalid_flow_target(tmp_path):
    payload = _flat_template(ICS55_PARAMETERS_TEMPLATE)
    with pytest.raises(WorkspaceFlowTargetError):
        save_workspace_config(tmp_path, payload, {"start": "Harden", "end": "Synthesis"})
    assert not workspace_config_path(tmp_path).exists()


def test_save_drops_null_values_with_a_warning(tmp_path):
    payload = _flat_template(ICS55_PARAMETERS_TEMPLATE)
    payload["broken"] = None
    assert save_workspace_config(tmp_path, payload) is True
    loaded = load_workspace_config(tmp_path)
    assert "broken" not in loaded
    assert loaded["design"] == payload["design"]


def test_flow_validation_none_and_empty_pass():
    assert validate_flow_config(None) == {}
    assert validate_flow_config({}) == {}


def test_load_rejects_malformed_toml(tmp_path):
    workspace_config_path(tmp_path).parent.mkdir(parents=True)
    workspace_config_path(tmp_path).write_text("[flow\npreset =")
    with pytest.raises(WorkspaceConfigError):
        load_workspace_config(tmp_path)


def test_load_flow_violation_raises(tmp_path):
    payload = _flat_template(ICS55_PARAMETERS_TEMPLATE)
    save_workspace_config(tmp_path, payload, {"preset": "rtl2gds"})
    text = workspace_config_path(tmp_path).read_text()
    bad_flow = 'preset = "rtl2gds"\nstart = "Synthesis"\nend = "Harden"'
    workspace_config_path(tmp_path).write_text(text.replace('preset = "rtl2gds"', bad_flow))
    with pytest.raises(WorkspaceFlowTargetError):
        load_workspace_config(tmp_path)


def test_missing_flow_section_derives_from_flow_ledger(tmp_path):
    import json

    payload = _flat_template(ICS55_PARAMETERS_TEMPLATE)
    save_workspace_config(tmp_path, payload)
    steps = {
        "steps": [
            {"name": "Synthesis", "tool": "yosys", "state": "Success"},
            {"name": "filler", "tool": "ecc", "state": "Success"},
        ]
    }
    (tmp_path / "home" / "flow.json").write_text(json.dumps(steps))

    loaded = load_workspace_config(tmp_path)
    assert loaded["_flow"] == {"start": "Synthesis", "end": "filler"}


def test_missing_flow_and_missing_ledger_falls_back_to_empty(tmp_path):
    payload = _flat_template(ICS55_PARAMETERS_TEMPLATE)
    save_workspace_config(tmp_path, payload)
    loaded = load_workspace_config(tmp_path)
    assert loaded["_flow"] == {}


def test_chip_identity_flat_payload():
    assert parameters_have_chip_identity({"pdk": "ics55"})
    assert parameters_have_chip_identity({"design": "gcd"})
    assert parameters_have_chip_identity({"top_module": "gcd"})
    assert parameters_have_chip_identity({"clock": "clk"})
    assert parameters_have_chip_identity({"die": {"area": 100}})
    assert not parameters_have_chip_identity({"die": {"area": 0}})
    assert not parameters_have_chip_identity({})
    assert not parameters_have_chip_identity("not a dict")


def test_chip_identity_rejects_legacy_long_keys():
    legacy = {"PDK": "ics55", "Design": "gcd", "Top module": "gcd", "Clock": "clk"}
    assert not parameters_have_chip_identity(legacy)


def test_canonical_chain_and_preset_ranges():
    chain = canonical_flow_chain()
    assert chain[0] == "Synthesis"
    assert chain[-1] == "Harden"
    assert "RCX" in chain and "sta" in chain

    assert flow_range_for_preset("rtl2gds") == ("Synthesis", "Harden")
    assert flow_range_for_preset("synthesis_lec") == ("Synthesis", "lec")


def test_flow_range_of_section_forms():
    assert flow_range_of({}) is None
    assert flow_range_of({"preset": "rtl2gds"}) == ("Synthesis", "Harden")
    assert flow_range_of({"start": "place", "end": "route"}) == ("place", "route")


def test_flow_steps_in_range():
    assert flow_steps_in_range("RCX", "sta") == ["RCX", "sta"]
    with pytest.raises(WorkspaceFlowTargetError):
        flow_steps_in_range("nope", "sta")


def test_flow_section_from_flow_config_range():
    section = flow_section_from_flow_config({"start_step": "Place", "end_step": "Route"})
    assert section == {"start": "place", "end": "route"}


def test_flow_section_from_flow_config_non_contiguous_degrades(caplog):
    with caplog.at_level("WARNING"):
        section = flow_section_from_flow_config({"steps": ["Synth", "Place", "CTS"]})
    assert section == {"start": "Synthesis", "end": "CTS"}
    assert any("non-contiguous" in record.message for record in caplog.records)


def test_flow_section_from_flow_config_empty():
    assert flow_section_from_flow_config(None) == {}
    assert flow_section_from_flow_config({}) == {}


def test_flow_validation_rejects_unknown_preset():
    with pytest.raises(WorkspaceFlowTargetError):
        validate_flow_config({"preset": "does_not_exist"})


def test_save_replace_and_cleanup_failure_returns_false(
    tmp_path, monkeypatch, stubborn_candidate_unlink
):
    """A replace failure must surface as the documented False even when the
    temp-candidate cleanup itself fails — cleanup never aborts the caller."""
    payload = _flat_template(ICS55_PARAMETERS_TEMPLATE)

    def failing_replace(*args, **kwargs):
        raise OSError("injected replace failure")

    monkeypatch.setattr("chipcompiler.data.workspace_config.os.replace", failing_replace)

    assert save_workspace_config(tmp_path, payload) is False
    assert not workspace_config_path(tmp_path).exists()


def test_load_normalizes_legacy_long_keys(tmp_path):
    """AC-1: a hand-written params.toml with legacy long keys loads canonical."""
    from chipcompiler.data.workspace_config import load_workspace_config

    home = tmp_path / "home"
    home.mkdir()
    (home / "params.toml").write_text(
        '[design]\nname = "gcd"\ntop = "gcd"\nclock_port = "clk"\n'
        '\n[pdk]\nname = "ics55"\nroot = "/pdk"\n'
        '\n[params]\n"Max fanout" = 48\n"Target density" = 0.7\n'
    )

    payload = load_workspace_config(tmp_path)

    assert payload["max_fanout"] == 48
    assert payload["target_density"] == 0.7
    assert "Max fanout" not in payload
    assert "Target density" not in payload


def test_load_rejects_non_table_sections(tmp_path):
    workspace_config_path(tmp_path).parent.mkdir(parents=True)
    workspace_config_path(tmp_path).write_text("params = [1]\n")
    with pytest.raises(WorkspaceConfigError):
        load_workspace_config(tmp_path)


def test_derive_flow_ignores_non_list_ledger_steps(tmp_path):
    workspace_config_path(tmp_path).parent.mkdir(parents=True)
    workspace_config_path(tmp_path).write_text("[params]\n")
    (tmp_path / "home" / "flow.json").write_text('{"steps": 1}')

    loaded = load_workspace_config(tmp_path)

    assert loaded["_flow"] == {}


def test_save_refuses_symlinked_config_target(tmp_path):
    from chipcompiler.data.workspace_config import save_workspace_config

    workspace_dir = tmp_path / "ws"
    (workspace_dir / "home").mkdir(parents=True)
    external = tmp_path / "external.toml"
    external.write_text('[params]\ndesign = "external"\n')
    (workspace_dir / "home" / "params.toml").symlink_to(external)

    ok = save_workspace_config(str(workspace_dir), {"design": "gcd"}, None)

    assert ok is False
    assert external.read_text() == '[params]\ndesign = "external"\n'
    assert workspace_config_path(workspace_dir).is_symlink()


def test_save_refuses_symlinked_home_parent(tmp_path):
    from chipcompiler.data.workspace_config import save_workspace_config

    workspace_dir = tmp_path / "ws"
    external_home = tmp_path / "external-home"
    external_home.mkdir()
    workspace_dir.mkdir()
    (workspace_dir / "home").symlink_to(external_home, target_is_directory=True)

    ok = save_workspace_config(str(workspace_dir), {"design": "gcd"}, None)

    assert ok is False
    assert not (external_home / "params.toml").exists()


def test_migration_refuses_symlinked_home_parent(tmp_path):
    from chipcompiler.data.workspace_config import migrate_legacy_parameters

    workspace_dir = tmp_path / "ws"
    external_home = tmp_path / "external-home"
    external_home.mkdir()
    (external_home / "parameters.json").write_text('{"Design": "gcd"}')
    workspace_dir.mkdir()
    (workspace_dir / "home").symlink_to(external_home, target_is_directory=True)

    migrate_legacy_parameters(workspace_dir)

    assert (external_home / "parameters.json").exists()
    assert not (external_home / "params.toml").exists()


def test_migration_refuses_symlinked_legacy_parameters_file(tmp_path):
    from chipcompiler.data.workspace_config import migrate_legacy_parameters

    workspace_dir = tmp_path / "ws"
    (workspace_dir / "home").mkdir(parents=True)
    external = tmp_path / "external.json"
    external.write_text('{"Design": "gcd"}')
    (workspace_dir / "home" / "parameters.json").symlink_to(external)

    migrate_legacy_parameters(workspace_dir)

    assert not (workspace_dir / "home" / "params.toml").exists()
    assert (workspace_dir / "home" / "parameters.json").is_symlink()


def test_save_drops_null_values_instead_of_failing(tmp_path):
    from chipcompiler.data.workspace_config import load_workspace_config, save_workspace_config

    workspace_dir = tmp_path / "ws"
    ok = save_workspace_config(
        str(workspace_dir),
        {"design": "gcd", "top_module": "gcd", "pdk_config": None, "core": {"margin": None}},
        None,
    )

    assert ok is True
    loaded = load_workspace_config(workspace_dir)
    assert loaded["design"] == "gcd"
    assert "pdk_config" not in loaded
    assert "margin" not in loaded["core"]


def test_save_drops_null_list_elements_with_a_warning(tmp_path):
    ok = save_workspace_config(
        str(tmp_path),
        {"design": "gcd", "top_module": "gcd", "core": {"margin": [None, 2]}},
        None,
    )

    assert ok is True
    loaded = load_workspace_config(tmp_path)
    assert loaded["core"]["margin"] == [2]
