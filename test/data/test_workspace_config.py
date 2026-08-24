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


def test_flow_validation_accepts_display_name_aliases():
    assert validate_flow_config({"start": "Synth", "end": "Filler"}) == {
        "start": "Synthesis",
        "end": "filler",
    }


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


def test_missing_flow_section_falls_back_to_empty(tmp_path):
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
