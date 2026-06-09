#!/usr/bin/env python

import json
from pathlib import Path

from chipcompiler.data import create_workspace, load_workspace
from chipcompiler.data.workspace import (
    init_workspace_config,
    prepare_workspace_for_rerun,
    refresh_workspace_config,
    sync_workspace_config_to_parameters,
)
from chipcompiler.utility import json_read, json_write


def _create_minimal_ics55_pdk(root: Path) -> Path:
    tech_path = root / "prtech" / "techLEF" / "N551P6M_ecos.lef"
    tech_path.parent.mkdir(parents=True, exist_ok=True)
    tech_path.write_text("VERSION 5.8 ;\n")

    stdcell_root = root / "IP" / "STD_cell" / "ics55_LLSC_H7C_V1p10C100"
    for flavor in ("ics55_LLSC_H7CR", "ics55_LLSC_H7CL"):
        lef_path = stdcell_root / flavor / "lef" / f"{flavor}_ecos.lef"
        lef_path.parent.mkdir(parents=True, exist_ok=True)
        lef_path.write_text("VERSION 5.8 ;\n")

        lib_path = stdcell_root / flavor / "liberty" / f"{flavor}_ss_rcworst_1p08_125_nldm.lib"
        lib_path.parent.mkdir(parents=True, exist_ok=True)
        lib_path.write_text("library(test) { }\n")

    return root


def _default_parameters() -> dict:
    return {
        "PDK": "ics55",
        "Design": "gcd",
        "Top module": "gcd",
        "Clock": "clk",
        "Frequency max [MHz]": 100,
    }


def test_create_workspace_persists_pdk_root_in_parameters(tmp_path):
    pdk_root = _create_minimal_ics55_pdk(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters=_default_parameters(),
        pdk_root=str(pdk_root),
    )

    assert workspace is not None
    resolved_root = str(pdk_root.resolve())
    assert workspace.pdk.root == resolved_root
    assert workspace.parameters.data.get("PDK Root") == resolved_root

    parameters_data = json.loads((workspace_dir / "home" / "parameters.json").read_text())
    assert parameters_data.get("PDK Root") == resolved_root


def test_load_workspace_restores_pdk_root_from_parameters(tmp_path):
    pdk_root = _create_minimal_ics55_pdk(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters=_default_parameters(),
        pdk_root=str(pdk_root),
    )

    loaded = load_workspace(str(workspace_dir))

    assert loaded is not None
    resolved_root = str(pdk_root.resolve())
    assert loaded.pdk.root == resolved_root
    assert loaded.parameters.data.get("PDK Root") == resolved_root
    assert all(path.startswith(resolved_root) for path in loaded.pdk.libs)


def test_workspace_config_refresh_uses_updated_parameters(tmp_path):
    pdk_root = _create_minimal_ics55_pdk(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters=_default_parameters(),
        pdk_root=str(pdk_root),
    )

    workspace = load_workspace(str(workspace_dir))
    params = json_read(str(workspace_dir / "home" / "parameters.json"))
    params["Max fanout"] = 88
    params["Global right padding"] = 13
    json_write(str(workspace_dir / "home" / "parameters.json"), params)

    init_workspace_config(workspace)

    fixfanout = json_read(workspace.config["fixFanout"])
    placement = json_read(workspace.config["place"])
    assert fixfanout["max_fanout"] == 88
    assert placement["PL"]["GP"]["global_right_padding"] == 13


def test_refresh_workspace_config_updates_all_parameter_derived_fields(tmp_path):
    pdk_root = _create_minimal_ics55_pdk(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters=_default_parameters(),
        pdk_root=str(pdk_root),
    )

    workspace = load_workspace(str(workspace_dir))
    params = json_read(str(workspace_dir / "home" / "parameters.json"))
    params["Max fanout"] = 91
    params["Global right padding"] = 17
    params["Bottom layer"] = "MET3"
    params["Top layer"] = "MET6"
    params["Target density"] = 0.42
    params["Target overflow"] = 0.07
    params["Cell padding x"] = 444
    params["Routability opt flag"] = 0
    json_write(str(workspace_dir / "home" / "parameters.json"), params)

    refresh_workspace_config(workspace)

    fixfanout = json_read(workspace.config["fixFanout"])
    placement = json_read(workspace.config["place"])
    db = json_read(workspace.config["db"])
    routing = json_read(workspace.config["route"])
    dreamplace = json_read(workspace.config["dreamplace"])

    assert fixfanout["max_fanout"] == 91
    assert placement["PL"]["GP"]["global_right_padding"] == 17
    assert db["LayerSettings"]["routing_layer_1st"] == "MET3"
    assert routing["RT"]["-bottom_routing_layer"] == "MET3"
    assert routing["RT"]["-top_routing_layer"] == "MET6"
    assert dreamplace["target_density"] == 0.42
    assert dreamplace["stop_overflow"] == 0.07
    assert dreamplace["cell_padding_x"] == 444
    assert dreamplace["routability_opt_flag"] == 0


def test_sync_workspace_config_to_parameters_updates_routing_layers_and_refreshes_peers(tmp_path):
    pdk_root = _create_minimal_ics55_pdk(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters=_default_parameters(),
        pdk_root=str(pdk_root),
    )

    workspace = load_workspace(str(workspace_dir))
    routing = json_read(workspace.config["route"])
    routing["RT"]["-bottom_routing_layer"] = "MET4"
    routing["RT"]["-top_routing_layer"] = "MET7"
    json_write(workspace.config["route"], routing)

    assert sync_workspace_config_to_parameters(workspace, workspace.config["route"]) is True
    refresh_workspace_config(workspace)

    params = json_read(str(workspace_dir / "home" / "parameters.json"))
    db = json_read(workspace.config["db"])
    assert params["Bottom layer"] == "MET4"
    assert params["Top layer"] == "MET7"
    assert db["LayerSettings"]["routing_layer_1st"] == "MET4"


def test_sync_workspace_config_to_parameters_ignores_unmanaged_fields(tmp_path):
    pdk_root = _create_minimal_ics55_pdk(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters=_default_parameters(),
        pdk_root=str(pdk_root),
    )

    workspace = load_workspace(str(workspace_dir))
    cts = json_read(workspace.config["CTS"])
    cts["skew_bound"] = 0.12
    json_write(workspace.config["CTS"], cts)
    before = json_read(str(workspace_dir / "home" / "parameters.json"))

    assert sync_workspace_config_to_parameters(workspace, workspace.config["CTS"]) is False

    after = json_read(str(workspace_dir / "home" / "parameters.json"))
    assert after == before


def test_prepare_workspace_for_rerun_deletes_old_artifacts_and_resets_home_state(tmp_path):
    pdk_root = _create_minimal_ics55_pdk(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters=_default_parameters(),
        pdk_root=str(pdk_root),
    )

    parameters_before = (workspace_dir / "home" / "parameters.json").read_text()
    config_before = (workspace_dir / "config" / "flow_config.json").read_text()
    origin_before = (workspace_dir / "origin" / "gcd.v").read_text()

    step_dir = workspace_dir / "floorplan_ecc"
    (step_dir / "output").mkdir(parents=True)
    (step_dir / "data").mkdir()
    (step_dir / "feature").mkdir()
    (step_dir / "report").mkdir()
    (step_dir / "log").mkdir()
    (step_dir / "output" / "gcd_floorplan.png").write_text("old layout")
    (step_dir / "feature" / "floorplan.db.inst_dist.png").write_text("old metric")
    (step_dir / "log" / "floorplan.log").write_text("old log")

    home_path = workspace_dir / "home" / "home.json"
    home = json_read(str(home_path))
    home["layout"] = str(step_dir / "output" / "gcd_floorplan.png")
    home["metrics"] = {"instances dist.": str(step_dir / "feature" / "floorplan.db.inst_dist.png")}
    home["monitor"] = {
        "step": ["Floorplan - init"],
        "memory": ["1"],
        "runtime": ["2"],
        "instance": [3],
        "frequency": [4.0],
    }
    json_write(str(home_path), home)

    flow_path = workspace_dir / "home" / "flow.json"
    json_write(
        str(flow_path),
        {
            "steps": [
                {
                    "name": "Floorplan",
                    "tool": "ecc",
                    "state": "Success",
                    "runtime": "0:03",
                    "peak memory (mb)": 99,
                    "info": {"kept": "yes"},
                }
            ]
        },
    )

    checklist_path = workspace_dir / "home" / "checklist.json"
    json_write(
        str(checklist_path),
        {
            "path": str(checklist_path),
            "checklist": [
                {
                    "step": "Floorplan",
                    "type": "Area",
                    "item": "check DIE area",
                    "state": "Success",
                }
            ],
        },
    )

    class FakeEngineFlow:
        def __init__(self):
            self.workspace_steps = [
                type("Step", (), {"directory": str(step_dir)})(),
            ]
            self.engine_db = object()
            self.clear_calls = 0
            self.create_calls = 0

        def clear_states(self):
            self.clear_calls += 1
            data = json_read(str(flow_path))
            for step in data["steps"]:
                step["state"] = "Unstart"
                step["runtime"] = ""
                step["peak memory (mb)"] = 0
            json_write(str(flow_path), data)

        def create_step_workspaces(self):
            self.create_calls += 1
            (step_dir / "output").mkdir(parents=True)
            (step_dir / "log").mkdir()
            self.workspace_steps = [type("Step", (), {"directory": str(step_dir)})()]

    engine_flow = FakeEngineFlow()

    prepare_workspace_for_rerun(workspace, engine_flow)

    assert step_dir.exists()
    assert not (step_dir / "output" / "gcd_floorplan.png").exists()
    assert not (step_dir / "feature" / "floorplan.db.inst_dist.png").exists()
    assert not (step_dir / "log" / "floorplan.log").exists()
    assert (workspace_dir / "config" / "flow_config.json").read_text() == config_before
    assert (workspace_dir / "origin" / "gcd.v").read_text() == origin_before
    assert (workspace_dir / "log").exists()

    reset_parameters = json.loads((workspace_dir / "home" / "parameters.json").read_text())
    parameters_before_json = json.loads(parameters_before)
    assert reset_parameters["PDK"] == parameters_before_json["PDK"]
    assert reset_parameters["Design"] == parameters_before_json["Design"]
    assert reset_parameters["Top module"] == parameters_before_json["Top module"]
    assert reset_parameters["Clock"] == parameters_before_json["Clock"]
    assert reset_parameters["Frequency max [MHz]"] == parameters_before_json["Frequency max [MHz]"]
    assert reset_parameters["Core"]["Utilitization"] == parameters_before_json["Core"]["Utilitization"]
    assert reset_parameters["Core"]["Margin"] == parameters_before_json["Core"]["Margin"]
    assert reset_parameters["Core"]["Aspect ratio"] == parameters_before_json["Core"]["Aspect ratio"]
    assert reset_parameters["Die"]["Size"] == []
    assert reset_parameters["Die"]["Area"] == 0
    assert reset_parameters["Core"]["Size"] == []
    assert reset_parameters["Core"]["Area"] == 0
    assert reset_parameters["Core"]["Bounding box"] == ""

    reset_home = json_read(str(home_path))
    assert reset_home["parameters"] == str(workspace_dir / "home" / "parameters.json")
    assert reset_home["flow"] == str(flow_path)
    assert reset_home["checklist"] == str(checklist_path)
    assert reset_home["layout"] == ""
    assert reset_home["metrics"] == {}
    assert reset_home["monitor"]["step"] == []

    reset_flow = json_read(str(flow_path))
    assert reset_flow["steps"][0]["state"] == "Unstart"
    assert reset_flow["steps"][0]["runtime"] == ""
    assert reset_flow["steps"][0]["peak memory (mb)"] == 0

    assert json_read(str(checklist_path)) == {
        "path": str(checklist_path),
        "checklist": [],
    }
    assert engine_flow.engine_db is None
    assert engine_flow.clear_calls == 1
    assert engine_flow.create_calls == 1


#SG13G2 workspace tests

def _create_minimal_sg13g2_pdk(root: Path) -> Path:
    """Create the minimal SG13G2 directory tree required by get_pdk()."""
    tech_path = root / "libs.ref" / "sg13g2_stdcell" / "lef" / "sg13g2_tech.lef"
    tech_path.parent.mkdir(parents=True, exist_ok=True)
    tech_path.write_text("VERSION 5.8 ;\n")

    lef_path = root / "libs.ref" / "sg13g2_stdcell" / "lef" / "sg13g2_stdcell.lef"
    lef_path.write_text("VERSION 5.8 ;\n")

    lib_path = root / "libs.ref" / "sg13g2_stdcell" / "lib" / "sg13g2_stdcell_typ_1p20V_25C.lib"
    lib_path.parent.mkdir(parents=True, exist_ok=True)
    lib_path.write_text("library(test) { }\n")

    return root


def _sg13g2_default_parameters() -> dict:
    return {
        "PDK": "sg13g2",
        "Design": "gcd",
        "Top module": "gcd",
        "Clock": "clk",
        "Frequency max [MHz]": 100,
    }


def test_create_workspace_sg13g2_persists_pdk_root_in_parameters(tmp_path):
    pdk_root = _create_minimal_sg13g2_pdk(tmp_path / "sg13g2")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="sg13g2",
        parameters=_sg13g2_default_parameters(),
        pdk_root=str(pdk_root),
    )

    assert workspace is not None
    resolved_root = str(pdk_root.resolve())
    assert workspace.pdk.root == resolved_root
    assert workspace.parameters.data.get("PDK Root") == resolved_root

    parameters_data = json.loads((workspace_dir / "home" / "parameters.json").read_text())
    assert parameters_data.get("PDK Root") == resolved_root


def test_load_workspace_sg13g2_restores_pdk_root_from_parameters(tmp_path):
    pdk_root = _create_minimal_sg13g2_pdk(tmp_path / "sg13g2")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="sg13g2",
        parameters=_sg13g2_default_parameters(),
        pdk_root=str(pdk_root),
    )

    loaded = load_workspace(str(workspace_dir))

    assert loaded is not None
    resolved_root = str(pdk_root.resolve())
    assert loaded.pdk.root == resolved_root
    assert loaded.parameters.data.get("PDK Root") == resolved_root
    assert all(path.startswith(resolved_root) for path in loaded.pdk.libs)
