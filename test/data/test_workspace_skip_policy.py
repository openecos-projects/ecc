"""Skip-policy behavior exercised through data.create_workspace.

Moved out of test_workspace.py (over the module-size guideline): each
test pins one ledger-level skip-policy contract — validation before
mutation, chaining under each policy, and policy-only persistence.
"""

from copy import deepcopy

import pytest

from chipcompiler.data import create_workspace, load_workspace
from chipcompiler.utility import json_read


def test_create_workspace_rejects_invalid_skip_steps_before_any_mutation(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    netlist_path = tmp_path / "gcd.v"
    netlist_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    with pytest.raises(ValueError, match="skip_steps"):
        create_workspace(
            directory=workspace_dir,
            origin_def="",
            origin_verilog=netlist_path,
            pdk="ics55",
            parameters=deepcopy(default_ics55_parameters),
            pdk_root=pdk_root,
            flow_config={"start_step": "Synthesis", "end_step": "Harden", "skip_steps": "lec"},
        )

    assert not workspace_dir.exists()


def test_create_workspace_default_policy_keeps_lec_out_of_the_ledger(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    """No declared policy: the synthesis LEC never enters the ledger, so
    preFloorplan directly follows synthesis and consumes its outputs."""
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    def_path = tmp_path / "gcd.def"
    def_path.write_text("VERSION 5.8 ;\nDESIGN gcd ;\nEND DESIGN\n")
    netlist_path = tmp_path / "gcd.v"
    netlist_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=workspace_dir,
        origin_def=def_path,
        origin_verilog=netlist_path,
        pdk="ics55",
        parameters=deepcopy(default_ics55_parameters),
        pdk_root=pdk_root,
        flow_config={"start_step": "Synthesis", "end_step": "preFloorplan"},
    )

    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [step["name"] for step in flow_data["steps"]] == ["Synthesis", "preFloorplan"]
    assert [step["tool"] for step in flow_data["steps"]] == ["yosys", "ecc"]


def test_create_workspace_explicit_empty_skip_enables_lec_in_the_ledger(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    """skip_steps = [] is the only LEC enable: the ledger carries the LEC
    entry (with the golden netlist recorded) and preFloorplan still follows
    the synthesis side of the chain."""
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    def_path = tmp_path / "gcd.def"
    def_path.write_text("VERSION 5.8 ;\nDESIGN gcd ;\nEND DESIGN\n")
    netlist_path = tmp_path / "gcd.v"
    netlist_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=workspace_dir,
        origin_def=def_path,
        origin_verilog=netlist_path,
        pdk="ics55",
        parameters=deepcopy(default_ics55_parameters),
        pdk_root=pdk_root,
        flow_config={"start_step": "Synthesis", "end_step": "preFloorplan", "skip_steps": []},
    )

    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [(step["name"], step["tool"]) for step in flow_data["steps"]] == [
        ("Synthesis", "yosys"),
        ("lec", "yosys_lec"),
        ("preFloorplan", "ecc"),
    ]


def test_create_workspace_skip_timing_opt_chains_route_after_legalization(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    netlist_path = tmp_path / "gcd.v"
    netlist_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=workspace_dir,
        origin_def="",
        origin_verilog=netlist_path,
        pdk="ics55",
        parameters=deepcopy(default_ics55_parameters),
        pdk_root=pdk_root,
        flow_config={
            "start_step": "legalization",
            "end_step": "route",
            "skip_steps": ["TimingOpt"],
        },
    )

    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [(step["name"], step["tool"]) for step in flow_data["steps"]] == [
        ("legalization", "dreamplace"),
        ("route", "ecc"),
    ]


def test_create_workspace_skip_post_route_lec_chains_drc_after_lvs(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    netlist_path = tmp_path / "gcd.v"
    netlist_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=workspace_dir,
        origin_def="",
        origin_verilog=netlist_path,
        pdk="ics55",
        parameters=deepcopy(default_ics55_parameters),
        pdk_root=pdk_root,
        flow_config={
            "start_step": "lvs",
            "end_step": "drc",
            "skip_steps": ["postRouteLec"],
        },
    )

    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [(step["name"], step["tool"]) for step in flow_data["steps"]] == [
        ("lvs", "ecc"),
        ("drc", "ecc"),
    ]


def test_create_workspace_policy_only_config_persists_declared_policy(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    """A policy-only flow config (no selected steps) still persists the
    declared policy, so ledger-less rebuilds resolve the same chain."""
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    netlist_path = tmp_path / "gcd.v"
    netlist_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=workspace_dir,
        origin_def="",
        origin_verilog=netlist_path,
        pdk="ics55",
        parameters=deepcopy(default_ics55_parameters),
        pdk_root=pdk_root,
        flow_config={"skip_steps": []},
    )

    assert workspace is not None
    assert not (workspace_dir / "home" / "flow.json").exists()
    loaded = load_workspace(str(workspace_dir))
    assert loaded.parameters.data["_flow"] == {"skip_steps": []}
