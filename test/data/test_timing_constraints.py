"""Initial workspace creation publishes both timing sets before any EDA step."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from chipcompiler.data import create_workspace, load_workspace, refresh_workspace_config
from chipcompiler.data.parameter import save_parameter
from chipcompiler.data.workspace.timing_constraints import scenario_tcl_path, timing_scenarios


@pytest.fixture
def sta_template():
    path = Path(__file__).resolve().parents[2] / "chipcompiler/tools/ecc/configs/sta_ecc.json"
    return json.loads(path.read_text())


def test_workspace_initialization_generates_both_sets_and_refreshes_parameters(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters, gcd_rtl_file
):
    workspace = create_workspace(
        directory=tmp_path / "run",
        origin_def="",
        origin_verilog=gcd_rtl_file,
        pdk="ics55",
        pdk_root=minimal_ics55_pdk_factory(tmp_path / "pdk"),
        parameters=default_ics55_parameters,
        flow_config={"preset": "rtl2gds", "skip_steps": []},
    )
    assert workspace is not None
    expected = {
        scenario_tcl_path(workspace.directory, scenario, post_cts=post_cts)
        for scenario in timing_scenarios(workspace)
        for post_cts in (False, True)
    }
    assert set((workspace.directory / "origin").rglob("*.tcl")) == expected
    for scenario in timing_scenarios(workspace):
        pre = scenario_tcl_path(workspace.directory, scenario, post_cts=False).read_text()
        post = scenario_tcl_path(workspace.directory, scenario, post_cts=True).read_text()
        assert post.startswith(pre)
        assert "set_propagated_clock" not in pre
        assert post.endswith("set_propagated_clock [all_clocks]\n")
    assert "steps" in workspace.flow.data
    assert all(entry["state"] == "Unstart" for entry in workspace.flow.data["steps"])

    loaded = load_workspace(workspace.directory)
    loaded.parameters.data["frequency_max"] = 250
    assert save_parameter(loaded.parameters)
    refresh_workspace_config(loaded)
    assert all("set clk_freq_mhz 250.0" in path.read_text() for path in expected)


def test_workspace_with_custom_full_constraints_does_not_generate_default_sets(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters, gcd_rtl_file
):
    custom = tmp_path / "constraints.sdc"
    content = b"# custom \xff\ncreate_clock -period 5 [get_ports clk]\n"
    custom.write_bytes(content)
    workspace = create_workspace(
        directory=tmp_path / "run",
        origin_def="",
        origin_verilog=gcd_rtl_file,
        pdk="ics55",
        pdk_root=minimal_ics55_pdk_factory(tmp_path / "pdk"),
        parameters=default_ics55_parameters,
        sdc=custom,
    )
    assert workspace is not None
    assert workspace.pdk.sdc is not None
    assert workspace.pdk.sdc.read_bytes() == content
    assert list((workspace.directory / "origin").rglob("*.tcl")) == []


@pytest.mark.parametrize("override_keys", [("liberty",), ("signoff",), ("liberty", "signoff")])
def test_selected_sta_corners_do_not_reduce_generated_constraint_sets(
    tmp_path,
    minimal_ics55_pdk_factory,
    default_ics55_parameters,
    gcd_rtl_file,
    sta_template,
    override_keys,
):
    template = sta_template
    max_library = next(item for item in template["liberty"] if item["corner"] == "MAX")
    choices = {
        "liberty": [{**max_library, "path": ["liberty/custom.lib"]}],
        "signoff": [{"MAX": ["Cworst"]}],
    }
    overrides = {key: choices[key] for key in override_keys}
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "pdk")
    workspace = create_workspace(
        directory=tmp_path / "run",
        origin_def="",
        origin_verilog=gcd_rtl_file,
        pdk="ics55",
        pdk_root=pdk_root,
        parameters={
            **default_ics55_parameters,
            "config_overrides": {"sta": overrides},
        },
    )
    assert workspace is not None
    temperatures = {item["corner"]: str(item["temperature"]) for item in template["liberty"]}
    expected_scripts = {
        workspace.directory
        / "origin"
        / phase
        / f"{corner}_{temperatures[corner].replace('-', 'm').replace('.', 'p')}_{rc}.tcl"
        for phase in ("pre_CTS", "post_CTS")
        for group in template["signoff"]
        for corner, rc_corners in group.items()
        for rc in rc_corners
    }
    expected_sta = deepcopy(template | overrides)
    for library in expected_sta["liberty"]:
        library["path"] = [str(pdk_root / path.lstrip("/")) for path in library["path"]]
    assert set((workspace.directory / "origin").rglob("*.tcl")) == expected_scripts
    assert json.loads(workspace.config["sta"].read_text()) == expected_sta

    loaded = load_workspace(workspace.directory)
    loaded.parameters.data["frequency_max"] = 250
    assert save_parameter(loaded.parameters)
    refresh_workspace_config(loaded)
    assert set((workspace.directory / "origin").rglob("*.tcl")) == expected_scripts
    assert all("set clk_freq_mhz 250.0" in path.read_text() for path in expected_scripts)
    assert json.loads(loaded.config["sta"].read_text()) == expected_sta
