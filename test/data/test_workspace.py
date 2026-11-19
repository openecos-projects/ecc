import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

import chipcompiler.data as data_api
import chipcompiler.data.workspace as workspace_data
from chipcompiler.data import (
    ChecklistItem,
    CheckOwner,
    CheckPolicy,
    CheckState,
    SkippableStepEnum,
    StepEnum,
    create_workspace,
    load_workspace,
)
from chipcompiler.data.flow.document import FlowStepEntry
from chipcompiler.data.step import StepDirectories
from chipcompiler.data.workspace import (
    Flow,
    Workspace,
    build_workspace_config_paths,
    init_workspace_config,
    prepare_workspace_for_rerun,
    refresh_workspace_config,
    update_step_config,
)
from chipcompiler.data.workspace.layout import EccData, EccOutput, EccStep, StepInput
from chipcompiler.utility import json_read, json_write
from test.flow_fixture import step_fields

EXPECTED_WORKSPACE_CONFIG_FILENAMES = {
    "db": "db_ecc.json",
    StepEnum.CTS.value: "cts_ecc.json",
    StepEnum.DRC.value: "drc_ecc.json",
    StepEnum.FLOORPLAN.value: "floorplan_ecc.json",
    "macro_location": "macro_location.tcl",
    StepEnum.ROUTING.value: "routing_ecc.json",
    StepEnum.FILLER.value: "filler_ecc.json",
    StepEnum.RCX.value: "rcx_ecc.json",
    StepEnum.STA.value: "sta_ecc.json",
    "sizer": "sizer_ecc.json",
    StepEnum.EMIR.value: "emir_ecc.json",
    "dreamplace": "dreamplace_ecc.json",
}

ROUTABILITY_FLAG_STRING_CASES = (
    ("true", 1),
    ("false", 0),
    ("2", 2),
    ("maybe", 1),
)


def test_flow_has_step_uses_cached_data_and_path(tmp_path):
    steps: list[FlowStepEntry] = [
        {
            "name": StepEnum.SYNTHESIS.value,
            "tool": "yosys",
            "state": "Unstart",
            **step_fields(StepEnum.SYNTHESIS.value, "yosys"),
        },
        {
            "name": StepEnum.FLOORPLAN.value,
            "tool": "ecc",
            "state": "Unstart",
            **step_fields(StepEnum.FLOORPLAN.value, "ecc"),
        },
    ]
    flow = Flow(data={"schema_version": 3, "steps": steps})
    assert flow.has_step(StepEnum.SYNTHESIS)
    assert flow.has_step("synthesis", "yosys")
    assert not flow.has_step(StepEnum.SYNTHESIS, "ecc")
    floorplan = flow.get_step(StepEnum.FLOORPLAN)
    assert floorplan is not None
    assert floorplan["tool"] == "ecc"
    assert flow.get_step(StepEnum.PLACEMENT) is None

    path = tmp_path / "flow.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "steps": [
                    {
                        "name": StepEnum.FLOORPLAN.value,
                        "tool": "ecc",
                        "state": "Unstart",
                        **step_fields(StepEnum.FLOORPLAN.value, "ecc"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = Flow(path=path)
    assert loaded.has_step(StepEnum.FLOORPLAN)
    assert not loaded.has_step(StepEnum.SYNTHESIS)


def _read_parameters(path):
    """Read a workspace config (home/params.toml) as a flat parameter dict."""
    from chipcompiler.data.parameter import load_parameter

    return load_parameter(Path(path)).data


def _write_parameters(path, data):
    """Write a flat parameter dict back to a workspace config (home/params.toml)."""
    from chipcompiler.data.parameter import Parameters, save_parameter

    assert save_parameter(Parameters(path=Path(path), data=dict(data)))


def _create_loaded_ics55_workspace(
    tmp_path,
    workspace_name,
    minimal_ics55_pdk_factory,
    default_ics55_parameters,
) -> tuple[Path, Any]:
    pdk_root = minimal_ics55_pdk_factory(tmp_path / f"{workspace_name}_pdk")
    rtl_path = tmp_path / f"{workspace_name}.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / workspace_name
    create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters=deepcopy(default_ics55_parameters),
        pdk_root=str(pdk_root),
    )

    return workspace_dir, load_workspace(str(workspace_dir))


def test_create_workspace_returns_path_fields_and_persists_string_paths(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=workspace_dir,
        origin_def="",
        origin_verilog=rtl_path,
        pdk="ics55",
        parameters={**default_ics55_parameters, "config_overrides": {"cts": {"max_fanout": 37}}},
        pdk_root=pdk_root,
    )
    assert workspace is not None

    assert workspace is not None
    assert workspace.directory == workspace_dir.resolve()
    assert isinstance(workspace.directory, Path)
    assert isinstance(workspace.design.origin_verilog, Path)
    assert workspace.design.origin_def is None
    assert isinstance(workspace.flow.path, Path)
    assert isinstance(workspace.parameters.path, Path)
    assert all(isinstance(path, Path) for path in workspace.config.values())
    assert workspace.config["macro_location"].is_file()
    assert not (workspace_dir / "home" / "home.json").exists()
    assert not (workspace_dir / "home" / "home.json.lock").exists()

    cts = json_read(workspace.config[StepEnum.CTS.value])
    assert cts["max_fanout"] == 37
    assert cts["buffer_type"] == workspace.pdk.buffers

    from chipcompiler.engine.workspace.configuration import (
        build_workspace_configuration_projection,
    )

    projection = build_workspace_configuration_projection(workspace)
    assert projection["workspaceSpec"]["inputMode"] == "rtl"
    assert projection["workspaceSpec"]["inputs"] == [
        {"inputId": "rtl", "role": "rtl"},
        {"inputId": "sdc", "role": "sdc"},
    ]
    assert projection == build_workspace_configuration_projection(load_workspace(workspace_dir))


def test_create_workspace_rejects_existing_non_empty_directory(tmp_path):
    workspace_dir = tmp_path / "workspace"
    (workspace_dir / "home").mkdir(parents=True)
    (workspace_dir / "home" / "params.toml").write_text("schema_version = 4\n")

    workspace = create_workspace(
        directory=workspace_dir,
        origin_def="",
        origin_verilog="",
        pdk="ics55",
        parameters={},
    )
    assert workspace is None


def test_create_workspace_persists_dynamic_flow_steps(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    def_path = tmp_path / "gcd.def"
    def_path.write_text("VERSION 5.8 ;\nDESIGN gcd ;\nEND DESIGN\n")
    netlist_path = tmp_path / "gcd.v"
    netlist_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=workspace_dir,
        origin_def=def_path,
        origin_verilog=netlist_path,
        pdk="ics55",
        parameters=default_ics55_parameters,
        pdk_root=pdk_root,
        flow_config={
            "schema_version": 3,
            "start_step": "placement",
            "end_step": "drc",
            "steps": ["placement", "cts", "legalization", "routing", "drc"],
        },
    )
    assert workspace is not None

    assert workspace is not None
    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [step["name"] for step in flow_data["steps"]] == [
        "placement",
        "diff_sizing",
        "cts",
        "legalization",
        "timing_optimization",
        "routing",
        "filler",
        "lvs",
        "drc",
    ]
    assert [step["tool"] for step in flow_data["steps"]] == [
        "dreamplace",
        "dreamplace",
        "ecc",
        "dreamplace",
        "sizer",
        "ecc",
        "ecc",
        "ecc",
        "ecc",
    ]
    assert all(step["state"] == "Unstart" for step in flow_data["steps"])
    assert all(step["runtime"] == "" for step in flow_data["steps"])
    assert all(step["peak memory (mb)"] == 0 for step in flow_data["steps"])


def test_create_workspace_copies_external_lec_and_sta_inputs(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    netlist = tmp_path / "gcd.v"
    golden = tmp_path / "gcd_golden.v"
    spef = tmp_path / "gcd.spef"
    netlist.write_text("module gcd; endmodule\n")
    golden.write_text("module gcd; endmodule\n")
    spef.write_text('*SPEF "IEEE 1481-1998"\n')

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=workspace_dir,
        origin_def="",
        origin_verilog=netlist,
        golden_verilog=golden,
        spef=spef,
        pdk="ics55",
        parameters=default_ics55_parameters,
        pdk_root=pdk_root,
        flow_config={"start_step": "post_route_lec", "end_step": "post_route_lec"},
    )
    assert workspace is not None

    assert workspace is not None
    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert flow_data["steps"][0]["info"]["golden_verilog"] == str(
        workspace_dir / "origin" / "golden_gcd_golden.v"
    )
    assert (workspace_dir / "origin" / "gcd.spef").is_file()


def test_load_workspace_keeps_golden_prefixed_primary_netlist(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    # A primary netlist whose name starts with golden_ must keep its role:
    # creation never declared a golden netlist, and the persisted flow
    # ledger says so.
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "golden_gcd.v"
    rtl_path.write_text("module gcd; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=workspace_dir,
        origin_def="",
        origin_verilog=rtl_path,
        pdk="ics55",
        parameters=deepcopy(default_ics55_parameters),
        pdk_root=pdk_root,
        flow_config={"start_step": "synthesis", "end_step": "post_floorplan"},
    )

    loaded = load_workspace(str(workspace_dir))
    assert loaded is not None
    assert loaded.design.origin_verilog == workspace_dir / "origin" / "golden_gcd.v"
    assert loaded.design.golden_verilog is None


def test_load_workspace_restores_golden_from_persisted_flow_info(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    netlist = tmp_path / "gcd.v"
    golden = tmp_path / "gcd_golden.v"
    netlist.write_text("module gcd; endmodule\n")
    golden.write_text("module gcd; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=workspace_dir,
        origin_def="",
        origin_verilog=netlist,
        golden_verilog=golden,
        pdk="ics55",
        parameters=deepcopy(default_ics55_parameters),
        pdk_root=pdk_root,
        flow_config={
            "start_step": "post_route_lec",
            "end_step": "post_route_lec",
            "skip_steps": [],
        },
    )

    loaded = load_workspace(str(workspace_dir))
    assert loaded is not None
    assert loaded.design.origin_verilog == workspace_dir / "origin" / "gcd.v"
    assert loaded.design.golden_verilog == workspace_dir / "origin" / "golden_gcd_golden.v"


def test_create_workspace_non_contiguous_flow_seeds_both_stores_contiguous(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters, caplog
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    def_path = tmp_path / "gcd.def"
    def_path.write_text("VERSION 5.8 ;\nDESIGN gcd ;\nEND DESIGN\n")
    netlist_path = tmp_path / "gcd.v"
    netlist_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    with caplog.at_level("WARNING"):
        workspace = create_workspace(
            directory=workspace_dir,
            origin_def=def_path,
            origin_verilog=netlist_path,
            pdk="ics55",
            parameters=default_ics55_parameters,
            pdk_root=pdk_root,
            flow_config={"schema_version": 3, "steps": ["synthesis", "placement", "cts"]},
        )
    assert workspace is not None

    assert workspace is not None
    # Both stores carry the same contiguous first..last range.
    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [step["name"] for step in flow_data["steps"]] == [
        "synthesis",
        "pre_floorplan",
        "macro_placement",
        "post_floorplan",
        "preplace",
        "placement",
        "diff_sizing",
        "cts",
    ]
    assert workspace.parameters.data["_flow"] == {"start": "synthesis", "end": "cts"}
    assert any("non-contiguous" in record.message for record in caplog.records)


def test_create_workspace_derives_dynamic_flow_from_boundaries(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
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
        parameters=default_ics55_parameters,
        pdk_root=pdk_root,
        flow_config={
            "start_step": "placement",
            "end_step": "harden",
        },
    )

    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [step["name"] for step in flow_data["steps"]] == [
        "placement",
        "diff_sizing",
        "cts",
        "legalization",
        "timing_optimization",
        "routing",
        "filler",
        "lvs",
        "drc",
        "antenna_check",
        "post_route_lec",
        "rcx",
        "sta",
        "power_analysis",
        "emir",
        "harden",
    ]


def test_create_workspace_selects_post_route_lec_with_its_formal_tool(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    steps = ["lvs", "drc", "post_route_lec"]
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
        parameters=default_ics55_parameters,
        pdk_root=pdk_root,
        flow_config={
            "schema_version": 3,
            "start_step": "lvs",
            "end_step": steps[-1],
            "steps": steps,
        },
    )

    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [(step["name"], step["tool"]) for step in flow_data["steps"]] == [
        ("lvs", "ecc"),
        ("drc", "ecc"),
        ("antenna_check", "ecc"),
        ("post_route_lec", "kepler_formal"),
    ]


def test_create_workspace_from_step_output_copies_only_origin_inputs_and_rebuilds_flow(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    source_workspace = tmp_path / "source"
    floorplan_output = source_workspace / "floorplan_ecc" / "output"
    floorplan_output.mkdir(parents=True)
    source_process_dir = source_workspace / "legalization_dreamplace"
    source_process_dir.mkdir()
    (source_process_dir / "checklist.json").write_text('{"state":"success"}\n')
    (source_workspace / "home").mkdir()
    (source_workspace / "home" / "flow.json").write_text('{"steps":[{"state":"Success"}]}\n')
    def_path = floorplan_output / "gcd_Floorplan.def.gz"
    def_path.write_text("def from floorplan\n")
    netlist_path = floorplan_output / "gcd_Floorplan.v.gz"
    netlist_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    sdc_path = source_workspace / "origin" / "gcd.sdc"
    sdc_path.parent.mkdir()
    sdc_path.write_text("create_clock -name clk -period 10 [get_ports clk]\n")

    workspace_dir = tmp_path / "ws_0008"
    workspace = create_workspace(
        directory=workspace_dir,
        origin_def=def_path,
        origin_verilog=netlist_path,
        sdc=sdc_path,
        pdk="ics55",
        parameters=default_ics55_parameters,
        pdk_root=pdk_root,
        flow_config={
            "start_step": "placement",
            "end_step": "legalization",
        },
    )
    assert workspace is not None

    assert workspace is not None
    assert (workspace_dir / "origin" / "gcd_Floorplan.def.gz").read_text() == "def from floorplan\n"
    assert "module gcd" in (workspace_dir / "origin" / "gcd_Floorplan.v.gz").read_text()
    assert (workspace_dir / "origin" / "gcd.sdc").read_text() == sdc_path.read_text()
    assert not (workspace_dir / "floorplan_ecc").exists()
    assert not (workspace_dir / "legalization_dreamplace").exists()

    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [step["name"] for step in flow_data["steps"]] == [
        "placement",
        "diff_sizing",
        "cts",
        "legalization",
    ]
    assert all(step["state"] == "Unstart" for step in flow_data["steps"])
    assert all(step["runtime"] == "" for step in flow_data["steps"])
    assert all(step["peak memory (mb)"] == 0 for step in flow_data["steps"])


def test_build_flow_for_dynamic_workspace_initializes_step_metadata_files(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    def_path = tmp_path / "gcd_floorplan.def.gz"
    def_path.write_text("VERSION 5.8 ;\nDESIGN gcd ;\nEND DESIGN\n")
    netlist_path = tmp_path / "gcd_floorplan.v.gz"
    netlist_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=workspace_dir,
        origin_def=def_path,
        origin_verilog=netlist_path,
        pdk="ics55",
        parameters=default_ics55_parameters,
        pdk_root=pdk_root,
        flow_config={
            "start_step": "cts",
            "end_step": "cts",
        },
    )
    assert workspace is not None

    from chipcompiler.engine.workspace_flow import build_flow_for_workspace

    build_flow_for_workspace(workspace)

    step_dir = StepDirectories.at(workspace_dir).path("cts")
    assert step_dir.name == "01_cts_ecc"
    step_subflow = json_read(step_dir / "subflow.json")
    step_checklist = json_read(step_dir / "checklist.json")
    home_checklist = json_read(workspace_dir / "home" / "checklist.json")

    assert [step["name"] for step in step_subflow["steps"]] == [
        "load data",
        "run CTS",
        "save data",
        "analysis",
    ]
    assert all(step["state"] == "Unstart" for step in step_subflow["steps"])
    assert step_checklist["schema_version"] == 3
    assert step_checklist["kind"] == "signoff_checklist"
    assert step_checklist["checklist"] == []
    assert home_checklist["schema_version"] == 3
    assert home_checklist["kind"] == "signoff_checklist"
    flow_items = {item["id"]: item for item in home_checklist["checklist"]}
    assert "flow.routing.completed" not in flow_items
    assert home_checklist["status"] == "blocked"


def test_load_workspace_restores_path_fields_from_existing_json(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    def_path = tmp_path / "gcd.def"
    def_path.write_text("VERSION 5.8 ;\nDESIGN gcd ;\nEND DESIGN\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=workspace_dir,
        origin_def=def_path,
        origin_verilog=rtl_path,
        pdk="ics55",
        parameters=default_ics55_parameters,
        pdk_root=pdk_root,
    )

    loaded = load_workspace(workspace_dir)
    assert loaded is not None

    assert loaded is not None
    assert loaded.directory == workspace_dir.resolve()
    assert loaded.design.origin_verilog == workspace_dir.resolve() / "origin" / "gcd.v"
    assert loaded.design.origin_def == workspace_dir.resolve() / "origin" / "gcd.def"
    assert loaded.flow.path == workspace_dir.resolve() / "home" / "flow.json"
    assert loaded.parameters.path == workspace_dir.resolve() / "home" / "params.toml"
    assert all(isinstance(path, Path) for path in loaded.config.values())


def test_load_workspace_restores_systemverilog_origin(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.sv"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    def_path = tmp_path / "gcd.def"
    def_path.write_text("VERSION 5.8 ;\nDESIGN gcd ;\nEND DESIGN\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=workspace_dir,
        origin_def=def_path,
        origin_verilog=rtl_path,
        pdk="ics55",
        parameters=default_ics55_parameters,
        pdk_root=pdk_root,
    )

    loaded = load_workspace(workspace_dir, read_only=True)

    assert loaded is not None
    assert loaded.design.origin_verilog == workspace_dir.resolve() / "origin" / "gcd.sv"


def test_worker_can_hydrate_while_parent_owns_workspace_lock(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    import subprocess
    import sys

    from chipcompiler.utility.workspace_lock import workspace_lock

    workspace_dir, _workspace = _create_loaded_ics55_workspace(
        tmp_path, "workspace", minimal_ics55_pdk_factory, default_ics55_parameters
    )
    with workspace_lock(workspace_dir):
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from chipcompiler.data import load_workspace; "
                "assert load_workspace(sys.argv[1], read_only=True) is not None",
                str(workspace_dir),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    assert completed.returncode == 0, completed.stderr


def test_derived_snapshot_inputs_bind_to_final_workspace(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    from chipcompiler.engine.snapshot import (
        create_engineering_snapshot,
        read_engineering_snapshot_from_directory,
    )
    from chipcompiler.engine.workspace.derive import derive_workspace

    source, workspace = _create_loaded_ics55_workspace(
        tmp_path, "workspace", minimal_ics55_pdk_factory, default_ics55_parameters
    )
    from chipcompiler.engine.workspace.reset import build_flow_for_workspace

    engine_flow = build_flow_for_workspace(workspace)
    assert engine_flow.save()
    create_engineering_snapshot(workspace)
    original = (source / "home/engineering-snapshot.json").read_bytes()
    target = tmp_path / "derived"

    derive_workspace(source, target)

    snapshot = read_engineering_snapshot_from_directory(target)
    inputs = snapshot["workspaceBindings"]["inputs"]
    assert inputs
    for path in inputs.values():
        assert Path(path).is_relative_to(target)
        assert Path(path).is_file()
    assert ".staging-" not in json.dumps(snapshot)
    assert (source / "home/engineering-snapshot.json").read_bytes() == original


def test_build_workspace_config_paths_returns_path_objects(tmp_path):
    workspace = Workspace(directory=tmp_path / "workspace")

    paths = build_workspace_config_paths(workspace)

    assert paths["dir"] == tmp_path / "workspace" / "config"
    assert paths["db"] == tmp_path / "workspace" / "config" / "db_ecc.json"
    assert all(isinstance(path, Path) for path in paths.values())


def test_workspace_config_paths_match_build_workspace_config_paths(tmp_path):
    workspace_dir = tmp_path / "workspace"

    paths = data_api.workspace_config_paths(workspace_dir)
    existing = build_workspace_config_paths(Workspace(directory=workspace_dir))

    assert paths == existing
    assert paths["dir"] == workspace_dir / "config"
    assert set(paths) == {"dir", *EXPECTED_WORKSPACE_CONFIG_FILENAMES}
    assert all(isinstance(path, Path) for path in paths.values())
    for config_key, filename in EXPECTED_WORKSPACE_CONFIG_FILENAMES.items():
        assert paths[config_key] == workspace_dir / "config" / filename


def test_workspace_config_path_handles_known_and_unknown_keys(tmp_path):
    workspace_dir = tmp_path / "workspace"

    assert data_api.workspace_config_key_path(str(workspace_dir), "db") == (
        workspace_dir / "config" / "db_ecc.json"
    )
    assert data_api.workspace_config_key_path(workspace_dir, StepEnum.FILLER.value) == (
        workspace_dir / "config" / "filler_ecc.json"
    )
    assert data_api.workspace_config_key_path(workspace_dir, StepEnum.PLACEMENT.value) is None
    assert data_api.workspace_config_key_path(workspace_dir, StepEnum.LEGALIZATION.value) is None
    assert data_api.workspace_config_key_path(workspace_dir, "unknown") is None


def test_step_config_keys_return_workspace_config_keys():
    assert data_api.step_config_keys("cts", "ecc") == ("db", StepEnum.CTS.value)
    assert data_api.step_config_keys(StepEnum.PRE_FLOORPLAN, "ecc") == (
        "db",
        StepEnum.FLOORPLAN.value,
    )
    assert data_api.step_config_keys(StepEnum.MACRO_PLACEMENT, "dreamplace") == (
        "dreamplace",
        "macro_location",
    )
    assert data_api.step_config_keys(StepEnum.POST_FLOORPLAN, "ecc") == (
        "db",
        StepEnum.FLOORPLAN.value,
        "macro_location",
    )
    assert data_api.step_config_keys("placement", "ecc") == ("db",)
    assert data_api.step_config_keys(StepEnum.PLACEMENT, "ecc") == ("db",)
    assert data_api.step_config_keys(StepEnum.DIFF_SIZING, "dreamplace") == ("dreamplace", "sta")
    assert data_api.step_config_keys("legalization", "ecc") == ("db",)
    assert data_api.step_config_keys("filler", "ecc") == (
        "db",
        StepEnum.FILLER.value,
    )
    assert data_api.step_config_keys("sta", "ecc") == (
        "db",
        StepEnum.RCX.value,
        StepEnum.STA.value,
    )
    assert data_api.step_config_keys("placement", "dreamplace") == ("dreamplace", "sta")
    assert data_api.step_config_keys("legalization", "dreamplace") == ("dreamplace",)
    assert data_api.step_config_keys(SkippableStepEnum.TIMING_OPT, "sizer") == (
        "db",
        "sizer",
        "sta",
        "routing",
        "dreamplace",
    )
    assert data_api.step_config_keys("preplace", "sizer") == ("db", "sizer", "sta", "routing")
    assert data_api.step_config_keys("synthesis", "yosys") == ("db",)
    assert data_api.step_config_keys("post_route_lec", "kepler_formal") == ()
    assert data_api.step_config_keys("placement", None) == ()


def test_step_config_keys_accept_exact_internal_step_names_only():
    cases = [
        (StepEnum.POST_FLOORPLAN.value, StepEnum.FLOORPLAN.value),
        (StepEnum.ROUTING.value, StepEnum.ROUTING.value),
        (StepEnum.RCX.value, StepEnum.RCX.value),
        ("sta", StepEnum.STA.value),
    ]

    for token, config_key in cases:
        keys = data_api.step_config_keys(token, "ecc")
        assert keys[0] == "db"
        assert config_key in keys

    for cli_token in (
        "Floorplan",
        "place",
        "route",
        "CTS",
        "RCX",
    ):
        assert data_api.step_config_keys(cli_token, "ecc") == ()

    assert data_api.step_config_keys("placement", "ECC") == ()
    assert data_api.step_config_keys("placement", "not-a-tool") == ()


def test_step_config_paths_return_expected_and_existing_paths(tmp_path):
    workspace_dir = tmp_path / "workspace"
    config_dir = workspace_dir / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "cts_ecc.json").write_text("{}")

    assert data_api.step_config_paths(workspace_dir, "cts", "ecc") == (
        config_dir / "db_ecc.json",
        config_dir / "cts_ecc.json",
    )
    assert data_api.step_config_paths(workspace_dir, "cts", "ecc", existing_only=True) == (
        config_dir / "cts_ecc.json",
    )
    assert data_api.step_config_paths(str(workspace_dir), "placement", "dreamplace") == (
        config_dir / "dreamplace_ecc.json",
        config_dir / "sta_ecc.json",
    )
    assert data_api.step_config_paths(workspace_dir, "legalization", "dreamplace") == (
        config_dir / "dreamplace_ecc.json",
    )
    assert data_api.step_config_paths(workspace_dir, SkippableStepEnum.TIMING_OPT, "sizer") == (
        config_dir / "db_ecc.json",
        config_dir / "sizer_ecc.json",
        config_dir / "sta_ecc.json",
        config_dir / "routing_ecc.json",
        config_dir / "dreamplace_ecc.json",
    )
    assert data_api.step_config_paths(workspace_dir, "placement", "ECC") == ()


def test_workspace_config_metadata_is_private_and_step_enum_keyed():
    for public_name in (
        "WORKSPACE_CONFIG_FILENAMES",
        "STEP_CONFIG_KEYS",
        "WORKSPACE_STEP_BY_LOWER_NAME",
        "WORKSPACE_STEP_ALIASES",
    ):
        assert not hasattr(data_api, public_name)
        assert public_name not in data_api.__all__
        assert not hasattr(workspace_data, public_name)

    assert hasattr(workspace_data, "_WORKSPACE_CONFIG_FILENAMES")

    step_source = "".join(path.read_text() for path in Path("chipcompiler/data/step").glob("*.py"))
    assert "STEP_CONFIG" not in step_source
    assert "WORKSPACE_CONFIG" not in step_source


def test_workspace_data_does_not_import_cli_step_normalization():
    source = Path("chipcompiler/data/workspace/__init__.py").read_text()

    assert "chipcompiler.cli" not in source


def test_data_package_does_not_import_cli_modules():
    for source_path in Path("chipcompiler/data").rglob("*.py"):
        source = source_path.read_text()
        assert "from chipcompiler.cli" not in source, source_path
        assert "import chipcompiler.cli" not in source, source_path


def test_create_workspace_persists_pdk_root_in_parameters(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters=default_ics55_parameters,
        pdk_root=str(pdk_root),
    )
    assert workspace is not None

    assert workspace is not None
    resolved_root = pdk_root.resolve()
    assert workspace.pdk.root == resolved_root
    assert workspace.parameters.data.get("pdk_root") == str(resolved_root)

    parameters_data = _read_parameters(workspace_dir / "home" / "params.toml")
    assert parameters_data.get("pdk_root") == str(resolved_root)


def test_load_workspace_restores_pdk_root_from_parameters(
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

    loaded = load_workspace(str(workspace_dir))
    assert loaded is not None

    assert loaded is not None
    resolved_root = pdk_root.resolve()
    assert loaded.pdk.root == resolved_root
    assert loaded.parameters.data.get("pdk_root") == str(resolved_root)
    assert all(path.is_relative_to(resolved_root) for path in loaded.pdk.libs)


def test_load_workspace_external_pdk_recovers_origin_sdc_spef(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    tech = next((pdk_root / "prtech").rglob("*.lef"))
    lef = next(pdk_root.rglob("ics55_LLSC_H7CR_ecos.lef"))
    lib = next(pdk_root.rglob("*.lib"))
    sdc_source = tmp_path / "source.sdc"
    sdc_source.write_text("# sdc\n")
    spef_source = tmp_path / "source.spef"
    spef_source.write_text("# spef\n")
    pdk_json = tmp_path / "pdk.json"
    pdk_json.write_text(
        json.dumps(
            {
                "name": "ics55",
                "root": str(pdk_root),
                "tech": str(tech),
                "lefs": [str(lef)],
                "libs": [str(lib)],
                "sdc": str(sdc_source),
                "spef": str(spef_source),
            }
        )
    )
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters=default_ics55_parameters,
        pdk_json=str(pdk_json),
    )

    origin_sdc = (workspace_dir / "origin" / "source.sdc").resolve()
    origin_spef = (workspace_dir / "origin" / "source.spef").resolve()
    assert origin_sdc.is_file()
    assert origin_spef.is_file()

    sdc_source.unlink()
    spef_source.unlink()

    loaded = load_workspace(str(workspace_dir))
    assert loaded is not None

    assert loaded is not None
    assert loaded.pdk.sdc == origin_sdc
    assert loaded.pdk.spef == origin_spef


def test_workspace_config_refresh_uses_updated_parameters(
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

    workspace = load_workspace(str(workspace_dir))
    assert workspace is not None
    init_workspace_config(workspace)

    filler = json_read(workspace.config["filler"])
    assert filler == {"-min_filler_width": 1}


def test_refresh_workspace_config_updates_all_parameter_derived_fields(
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

    workspace = load_workspace(str(workspace_dir))
    assert workspace is not None
    from chipcompiler.data import save_parameter
    from chipcompiler.params import lookup_schema, update_workspace_param_value
    from test.flow_fixture import current_flow_document

    workspace.flow.data = current_flow_document(
        [{"name": "placement", "tool": "dreamplace", "state": "Unstart"}]
    )
    edits = {
        "cts.max_fanout": 91,
        "route.bottom_layer": "MET3",
        "route.top_layer": "MET6",
    }
    placement_edits = {
        "place.target_density": 0.42,
        "place.stop_overflow": 0.07,
        "place.cell_padding_x": 444,
        "place.routability_opt_flag": 0,
    }
    for param, value in edits.items():
        schema = lookup_schema(param)
        assert schema is not None
        update_workspace_param_value(workspace, schema, value)
    for param, value in placement_edits.items():
        schema = lookup_schema(param)
        assert schema is not None
        update_workspace_param_value(workspace, schema, value, step="placement")
    assert save_parameter(workspace.parameters)

    cts = json_read(workspace.config[StepEnum.CTS.value])
    cts["skew_bound"] = "0.13"
    json_write(workspace.config[StepEnum.CTS.value], cts)

    refresh_workspace_config(workspace)

    filler = json_read(workspace.config["filler"])
    db = json_read(workspace.config["db"])
    floorplan = json_read(workspace.config[StepEnum.FLOORPLAN.value])
    routing = json_read(workspace.config["routing"])
    cts = json_read(workspace.config[StepEnum.CTS.value])

    assert cts["max_fanout"] == 91
    assert cts["buffer_type"] == workspace.pdk.buffers
    assert cts["skew_bound"] == "0.13"
    assert filler == {"-min_filler_width": 1}
    assert db["LayerSettings"]["routing_layer_1st"] == "MET3"
    assert routing["RT"]["-bottom_routing_layer"] == "MET3"
    assert routing["RT"]["-top_routing_layer"] == "MET6"
    # DreamPlace values are step-scoped: the refresh keeps them for the step to replay.
    assert workspace.parameters.data["step_params"] == {"placement": placement_edits}
    assert floorplan["die_builder"] == {
        "mode": "die_util",
        "site_name": "core7",
        "margin": {
            "left_micron": 2,
            "right_micron": 2,
            "top_micron": 2,
            "bottom_micron": 2,
        },
        "die_util": {"aspect_ratio": 1, "utilization": 0.4},
        "die_size": {"width_micron": 100.1, "height_micron": 246.6},
    }
    assert floorplan["macro_placer"] == {
        "file_path": "",
        "macro_placement_halo": 3.0,
        "macro_routing_halo": 3.0,
    }
    assert floorplan["io_placer"] == {
        "mode": "auto",
        "file_path": "",
        "io_layer_list": ["MET3", "MET4"],
    }


def test_refresh_workspace_config_restores_missing_floorplan_fields(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    _, workspace = _create_loaded_ics55_workspace(
        tmp_path,
        "workspace_legacy_floorplan",
        minimal_ics55_pdk_factory,
        default_ics55_parameters,
    )
    config_path = workspace.config[StepEnum.FLOORPLAN.value]
    floorplan = json_read(config_path)
    floorplan["macro_placer"].pop("file_path")
    floorplan["io_placer"].pop("mode")
    floorplan["io_placer"].pop("file_path")
    json_write(config_path, floorplan)

    refresh_workspace_config(workspace)

    refreshed = json_read(config_path)
    assert refreshed["macro_placer"] == {
        "file_path": "",
        "macro_placement_halo": 3.0,
        "macro_routing_halo": 3.0,
    }
    assert refreshed["io_placer"] == {
        "mode": "auto",
        "file_path": "",
        "io_layer_list": ["MET3", "MET4"],
    }


def test_refresh_workspace_config_updates_generated_sdc_frequency(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    workspace_dir, workspace = _create_loaded_ics55_workspace(
        tmp_path,
        "workspace_generated_sdc",
        minimal_ics55_pdk_factory,
        default_ics55_parameters,
    )
    parameter_path = workspace_dir / "home" / "params.toml"
    params = _read_parameters(parameter_path)
    params["frequency_max"] = 250.0
    _write_parameters(parameter_path, params)

    refresh_workspace_config(workspace)

    assert "set clk_freq_mhz 250.0" in workspace.pdk.sdc.read_text(encoding="utf-8")


def test_refresh_workspace_config_preserves_external_sdc(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    workspace_dir, workspace = _create_loaded_ics55_workspace(
        tmp_path,
        "workspace_external_sdc",
        minimal_ics55_pdk_factory,
        default_ics55_parameters,
    )
    external_sdc = workspace.pdk.sdc
    external_content = "create_clock -period 1 [get_ports clk]\n"
    external_sdc.write_text(external_content, encoding="utf-8")
    params = _read_parameters(workspace_dir / "home" / "params.toml")
    params["frequency_max"] = 250.0
    _write_parameters(workspace_dir / "home" / "params.toml", params)

    refresh_workspace_config(workspace)

    assert external_sdc.read_text(encoding="utf-8") == external_content


def test_refresh_workspace_config_preserves_nested_dreamplace_override_precedence(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    workspace_dir, workspace = _create_loaded_ics55_workspace(
        tmp_path,
        "workspace_dreamplace_precedence",
        minimal_ics55_pdk_factory,
        default_ics55_parameters,
    )
    parameter_path = workspace_dir / "home" / "params.toml"
    params = _read_parameters(parameter_path)
    params["target_density"] = 0.25
    params["routability_opt_flag"] = "true"
    params["dreamplace"] = {
        "target_density": 0.88,
        "routability_opt_flag": 0,
    }
    _write_parameters(parameter_path, params)

    refresh_workspace_config(workspace)

    dreamplace = json_read(workspace.config["dreamplace"])
    assert dreamplace["target_density"] == 0.88
    assert dreamplace["routability_opt_flag"] == 0


def test_apply_config_overrides_validates_every_target_before_writing(tmp_path):
    from chipcompiler.data.workspace.config_overrides import apply_config_overrides

    cts_path = tmp_path / "cts.json"
    json_write(cts_path, {"skew_bound": "0.05"})
    parameters = {
        "config_overrides": {
            "cts.json": {"skew_bound": "0.20"},
            "bogus.json": {"threads": 1},
        }
    }

    with pytest.raises(ValueError, match="unknown config override target"):
        apply_config_overrides({"cts.json": cts_path}, parameters)

    # The valid first override is not persisted when a later target is invalid.
    assert json_read(cts_path) == {"skew_bound": "0.05"}


def test_refresh_workspace_config_reapplies_direct_config_overrides(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters={
            **default_ics55_parameters,
            "config_overrides": {
                "cts": {"skew_bound": "0.05", "buffer_type": []},
                "dreamplace": {"num_threads": 12},
            },
        },
        pdk_root=str(pdk_root),
    )
    assert workspace is not None

    cts = json_read(workspace.config[StepEnum.CTS.value])
    dreamplace = json_read(workspace.config["dreamplace"])
    assert cts["skew_bound"] == "0.05"
    assert cts["buffer_type"] == workspace.pdk.buffers
    assert dreamplace["num_threads"] == 12

    cts["skew_bound"] = "0.20"
    dreamplace["num_threads"] = 1
    json_write(workspace.config[StepEnum.CTS.value], cts)
    json_write(workspace.config["dreamplace"], dreamplace)

    refresh_workspace_config(workspace)

    cts = json_read(workspace.config[StepEnum.CTS.value])
    assert cts["skew_bound"] == "0.05"
    assert cts["buffer_type"] == workspace.pdk.buffers
    assert json_read(workspace.config["dreamplace"])["num_threads"] == 12


def test_refresh_workspace_config_expands_pdk_relative_sta_liberty_overrides(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    relative_liberty = [
        {
            "corner": "MAX",
            "temperature": 125,
            "path": [
                "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CR/liberty/ics55_LLSC_H7CR_ss_rcworst_1p08_125_nldm.lib"
            ],
        }
    ]
    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters={
            **default_ics55_parameters,
            "config_overrides": {"sta": {"liberty": deepcopy(relative_liberty)}},
        },
        pdk_root=str(pdk_root),
    )
    assert workspace is not None

    expected = [str(pdk_root / path.lstrip("/")) for path in relative_liberty[0]["path"]]
    sta = json_read(workspace.config[StepEnum.STA.value])
    assert sta["liberty"][0]["path"] == expected

    refresh_workspace_config(workspace)

    sta = json_read(workspace.config[StepEnum.STA.value])
    assert sta["liberty"][0]["path"] == expected


def test_update_step_config_keeps_sta_liberty_expanded_after_override_replay(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    relative_liberty = [
        {
            "corner": "MAX",
            "temperature": 125,
            "path": [
                "/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CR/liberty/ics55_LLSC_H7CR_ss_rcworst_1p08_125_nldm.lib"
            ],
        }
    ]
    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters={
            **default_ics55_parameters,
            "config_overrides": {"sta": {"liberty": deepcopy(relative_liberty)}},
        },
        pdk_root=str(pdk_root),
    )
    assert workspace is not None
    expected = [str(pdk_root / path.lstrip("/")) for path in relative_liberty[0]["path"]]

    step = EccStep(
        name=StepEnum.POST_FLOORPLAN.value,
        input=StepInput(),
        output=EccOutput(dir=workspace_dir / "post_floorplan_ecc" / "output"),
        data=EccData(
            steps={StepEnum.POST_FLOORPLAN.value: workspace_dir / "post_floorplan_ecc" / "data"}
        ),
    )

    update_step_config(workspace, step)

    sta = json_read(workspace.config[StepEnum.STA.value])
    assert sta["liberty"][0]["path"] == expected


def test_create_workspace_rejects_sta_liberty_with_invalid_io_timing(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    invalid_io_liberty = (
        "/IP/IO/ICsprout_55LLULP1233_IO_251013/liberty/ICSIOA_N55_3P3_ff_1p32_3p63_m40c.lib"
    )
    liberty = [{"corner": "MIN", "temperature": -40, "path": [invalid_io_liberty]}]

    with pytest.raises(ValueError) as exc_info:
        create_workspace(
            directory=str(tmp_path / "workspace"),
            origin_def="",
            origin_verilog=str(rtl_path),
            pdk="ics55",
            parameters={
                **default_ics55_parameters,
                "config_overrides": {"sta": {"liberty": liberty}},
            },
            pdk_root=str(pdk_root),
        )
    assert str(exc_info.value) == (
        "STA liberty validation failed:\n"
        "  ICS55 IO liberty has invalid rise timing tables: "
        f"{pdk_root / invalid_io_liberty.lstrip('/')}; "
        "use ICSIOA_N55_3P3_ff_1p32_3p63v_0c.lib instead"
    )


def test_refresh_sta_config_does_not_overwrite_corrupt_json(tmp_path):
    sta_path = tmp_path / "sta_ecc.json"
    workspace = Workspace(directory=tmp_path, config={StepEnum.STA.value: sta_path})
    workspace.pdk.root = tmp_path / "pdk"
    sta_path.write_text("{corrupt", encoding="utf-8")

    with pytest.raises(Exception):  # noqa: B017 - exact parser error is implementation-specific
        workspace_data._refresh_sta_config(workspace)
    assert sta_path.read_text(encoding="utf-8") == "{corrupt"


def test_update_step_config_preserves_floorplan_mode_override_after_result_backfill(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    workspace_dir, workspace = _create_loaded_ics55_workspace(
        tmp_path,
        "workspace_floorplan_mode_override",
        minimal_ics55_pdk_factory,
        default_ics55_parameters,
    )
    parameters = _read_parameters(workspace_dir / "home" / "params.toml")
    parameters["die"] = {"size": [31.8, 32.0], "area": 1017.6}
    parameters["config_overrides"] = {
        "floorplan": {"die_builder": {"mode": "die_util"}},
    }
    _write_parameters(workspace_dir / "home" / "params.toml", parameters)
    workspace.parameters.data = parameters

    step = EccStep(
        name=StepEnum.POST_FLOORPLAN.value,
        input=StepInput(),
        output=EccOutput(dir=workspace_dir / "post_floorplan_ecc" / "output"),
        data=EccData(
            steps={StepEnum.POST_FLOORPLAN.value: workspace_dir / "post_floorplan_ecc" / "data"}
        ),
    )

    update_step_config(workspace, step)

    floorplan = json_read(workspace.config[StepEnum.FLOORPLAN.value])
    assert floorplan["die_builder"]["mode"] == "die_util"


def test_prepare_workspace_for_rerun_deletes_old_artifacts_and_resets_runtime_state(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters=default_ics55_parameters,
        pdk_root=str(pdk_root),
    )
    assert workspace is not None

    parameters_before = _read_parameters(workspace_dir / "home" / "params.toml")
    config_before = (workspace_dir / "config" / "filler_ecc.json").read_text()
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
    flow_path = workspace_dir / "home" / "flow.json"
    json_write(
        flow_path,
        {
            "schema_version": 3,
            "steps": [
                {
                    "name": "floorplan",
                    "tool": "ecc",
                    "state": "Success",
                    "runtime": "0:03",
                    "peak memory (mb)": 99,
                    "info": {"kept": "yes"},
                    **step_fields("floorplan", "ecc"),
                }
            ],
        },
    )

    checklist_path = workspace_dir / "home" / "checklist.json"
    json_write(
        checklist_path,
        {
            "schema_version": 3,
            "kind": "signoff_checklist",
            "path": str(checklist_path),
            "checklist": [
                ChecklistItem(
                    id="pre_floorplan.check.die.area",
                    step="pre_floorplan",
                    category="area",
                    owner=CheckOwner.CHECKLIST,
                    policy=CheckPolicy.WARN,
                    state=CheckState.PASS,
                    title="check DIE area",
                ).to_record()
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
            data = json_read(flow_path)
            for step in data["steps"]:
                step["state"] = "Unstart"
                step["runtime"] = ""
                step["peak memory (mb)"] = 0
            json_write(flow_path, data)

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
    assert (workspace_dir / "config" / "filler_ecc.json").read_text() == config_before
    assert (workspace_dir / "origin" / "gcd.v").read_text() == origin_before
    assert (workspace_dir / "log").exists()

    reset_parameters = _read_parameters(workspace_dir / "home" / "params.toml")
    parameters_before_json = parameters_before
    assert reset_parameters["pdk"] == parameters_before_json["pdk"]
    assert reset_parameters["design"] == parameters_before_json["design"]
    assert reset_parameters["top_module"] == parameters_before_json["top_module"]
    assert reset_parameters["clock"] == parameters_before_json["clock"]
    assert reset_parameters["frequency_max"] == parameters_before_json["frequency_max"]
    assert (
        reset_parameters["core"]["utilitization"] == parameters_before_json["core"]["utilitization"]
    )
    assert reset_parameters["core"]["margin"] == parameters_before_json["core"]["margin"]
    assert (
        reset_parameters["core"]["aspect_ratio"] == parameters_before_json["core"]["aspect_ratio"]
    )
    assert reset_parameters["die"]["size"] == []
    assert reset_parameters["die"]["area"] == 0
    assert reset_parameters["core"]["size"] == []
    assert reset_parameters["core"]["area"] == 0
    assert reset_parameters["core"]["bounding_box"] == ""

    reset_flow = json_read(flow_path)
    assert reset_flow["steps"][0]["state"] == "Unstart"
    assert reset_flow["steps"][0]["runtime"] == ""
    assert reset_flow["steps"][0]["peak memory (mb)"] == 0

    reset_checklist = json_read(checklist_path)
    assert reset_checklist["schema_version"] == 3
    assert reset_checklist["kind"] == "signoff_checklist"
    assert reset_checklist["checklist"] == []
    assert engine_flow.engine_db is None
    assert engine_flow.clear_calls == 1
    assert engine_flow.create_calls == 1

    parameter_path = workspace_dir / "home" / "params.toml"
    preserved_parameters = _read_parameters(parameter_path)
    preserved_parameters["die"] = {"size": [120.0, 80.0], "area": 9600.0}
    preserved_parameters["core"] = {
        **preserved_parameters["core"],
        "size": [100.0, 60.0],
        "area": 6000.0,
        "bounding_box": "0 0 100 60",
    }
    _write_parameters(parameter_path, preserved_parameters)
    workspace.parameters.data = preserved_parameters
    preserved_parameter_text = parameter_path.read_text()
    assert preserved_parameter_text

    workspace.parameters.path = None
    prepare_workspace_for_rerun(
        workspace,
        FakeEngineFlow(),
        preserve_user_inputs=True,
    )

    assert parameter_path.read_text() == preserved_parameter_text
    assert workspace.parameters.path == parameter_path
    assert (workspace_dir / "config" / "filler_ecc.json").read_text() == config_before


def test_create_workspace_sg13g2_persists_pdk_root_in_parameters(
    tmp_path, minimal_sg13g2_pdk_factory, default_sg13g2_parameters
):
    pdk_root = minimal_sg13g2_pdk_factory(tmp_path / "sg13g2")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="sg13g2",
        parameters=default_sg13g2_parameters,
        pdk_root=str(pdk_root),
    )
    assert workspace is not None

    assert workspace is not None
    resolved_root = pdk_root.resolve()
    assert workspace.pdk.root == resolved_root
    assert workspace.parameters.data.get("pdk_root") == str(resolved_root)

    parameters_data = _read_parameters(workspace_dir / "home" / "params.toml")
    assert parameters_data.get("pdk_root") == str(resolved_root)


def test_load_workspace_sg13g2_restores_pdk_root_from_parameters(
    tmp_path, minimal_sg13g2_pdk_factory, default_sg13g2_parameters
):
    pdk_root = minimal_sg13g2_pdk_factory(tmp_path / "sg13g2")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="sg13g2",
        parameters=default_sg13g2_parameters,
        pdk_root=str(pdk_root),
    )

    loaded = load_workspace(str(workspace_dir))
    assert loaded is not None

    assert loaded is not None
    resolved_root = pdk_root.resolve()
    assert loaded.pdk.root == resolved_root
    assert loaded.parameters.data.get("pdk_root") == str(resolved_root)
    assert all(path.is_relative_to(resolved_root) for path in loaded.pdk.libs)


def test_create_workspace_with_pdk_overrides_str_branch(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters=default_ics55_parameters,
        pdk_root=str(pdk_root),
        pdk_overrides={"dont_use": ["ICG*"]},
    )
    assert workspace is not None

    assert workspace is not None
    assert workspace.pdk.dont_use == ["ICG*"]


def test_create_workspace_with_pdk_overrides_pdk_object_ignored(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    from chipcompiler.data.pdk import get_pdk

    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    pdk_obj = get_pdk("ics55", pdk_root=pdk_root)
    original_dont_use = pdk_obj.dont_use

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk=pdk_obj,
        parameters=default_ics55_parameters,
        pdk_overrides={"dont_use": ["ICG*"]},
    )
    assert workspace is not None

    assert workspace is not None
    assert workspace.pdk.dont_use == original_dont_use


def test_workspace_pdk_overrides_persisted_on_reload(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    layer_map = tmp_path / "layers.map"
    layer_map.write_text("MET1 1 0\n")

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters=default_ics55_parameters,
        pdk_root=str(pdk_root),
        pdk_overrides={"dont_use": ["ICG*"], "mapping_file": str(layer_map)},
    )
    assert workspace is not None
    assert workspace.pdk.dont_use == ["ICG*"]

    loaded = load_workspace(str(workspace_dir))
    assert loaded is not None

    assert loaded.pdk == workspace.pdk


def test_create_workspace_pdk_overrides_typo_propagates(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    import pytest

    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    with pytest.raises(ValueError, match="unknown PDK override fields"):
        create_workspace(
            directory=str(workspace_dir),
            origin_def="",
            origin_verilog=str(rtl_path),
            pdk="ics55",
            parameters=default_ics55_parameters,
            pdk_root=str(pdk_root),
            pdk_overrides={"dontuse": ["ICG*"]},
        )
