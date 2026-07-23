import json
from copy import deepcopy
from pathlib import Path

import chipcompiler.data as data_api
import chipcompiler.data.workspace as workspace_data
from chipcompiler.data import (
    OriginDesign,
    StepEnum,
    WorkspaceStep,
    create_workspace,
    load_workspace,
)
from chipcompiler.data.workspace import (
    Workspace,
    build_workspace_config_paths,
    init_workspace_config,
    prepare_workspace_for_rerun,
    refresh_workspace_config,
    sync_workspace_config_to_parameters,
    update_step_config,
)
from chipcompiler.utility import json_read, json_write

EXPECTED_WORKSPACE_CONFIG_FILENAMES = {
    "flow": "flow_config.json",
    "db": "db_default_config.json",
    StepEnum.CTS.value: "cts_default_config.json",
    StepEnum.DRC.value: "drc_default_config.json",
    StepEnum.FLOORPLAN.value: "fp_default_config.json",
    StepEnum.NETLIST_OPT.value: "no_default_config_fixfanout.json",
    StepEnum.PLACEMENT.value: "pl_default_config.json",
    StepEnum.PNP.value: "pnp_default_config.json",
    StepEnum.ROUTING.value: "rt_default_config.json",
    StepEnum.TIMING_OPT_DRV.value: "to_default_config_drv.json",
    StepEnum.TIMING_OPT_HOLD.value: "to_default_config_hold.json",
    StepEnum.TIMING_OPT_SETUP.value: "to_default_config_setup.json",
    StepEnum.LEGALIZATION.value: "pl_default_config.json",
    StepEnum.FILLER.value: "pl_default_config.json",
    StepEnum.RCX.value: "rcx.json",
    StepEnum.STA.value: "sta.json",
    "dreamplace": "dreamplace.json",
}

ROUTABILITY_FLAG_STRING_CASES = (
    ("true", 1),
    ("false", 0),
    ("2", 2),
    ("maybe", 1),
)


def test_rcx_step_config_uses_top_module_for_spef_paths(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    db_config = config_dir / "db.json"
    rcx_config = config_dir / "rcx.json"
    json_write(db_config, {"INPUT": {}, "OUTPUT": {}})
    json_write(
        rcx_config,
        {"corners": [{"name": "Cworst", "temperature": [125]}]},
    )
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="project_gcd_ws_0002", top_module="gcd"),
        config={"db": db_config, StepEnum.RCX.value: rcx_config},
    )
    step = WorkspaceStep(
        name=StepEnum.RCX.value,
        input={"def": None, "verilog": None},
        output={"dir": tmp_path / "RCX_ecc" / "output"},
    )

    update_step_config(workspace, step)

    assert json_read(rcx_config)["corners"][0]["spef_file"] == [
        {"125": str(tmp_path / "RCX_ecc" / "output" / "gcd_Cworst_125C.spef")}
    ]


def _create_loaded_ics55_workspace(
    tmp_path,
    workspace_name,
    minimal_ics55_pdk_factory,
    default_ics55_parameters,
):
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
        parameters=default_ics55_parameters,
        pdk_root=pdk_root,
    )

    assert workspace is not None
    assert workspace.directory == workspace_dir.resolve()
    assert isinstance(workspace.directory, Path)
    assert isinstance(workspace.design.origin_verilog, Path)
    assert isinstance(workspace.design.origin_def, Path)
    assert isinstance(workspace.flow.path, Path)
    assert isinstance(workspace.parameters.path, Path)
    assert isinstance(workspace.home.path, Path)
    assert all(isinstance(path, Path) for path in workspace.config.values())

    home_data = json.loads((workspace_dir / "home" / "home.json").read_text())
    assert home_data["flow"] == str(workspace.flow.path)
    assert home_data["parameters"] == str(workspace.parameters.path)
    assert home_data["checklist"] == str(workspace_dir.resolve() / "home" / "checklist.json")
    assert isinstance(home_data["flow"], str)

    flow_config = json_read(workspace.config["flow"])
    assert flow_config["ConfigPath"]["idb_path"] == str(workspace.config["db"])
    assert isinstance(flow_config["ConfigPath"]["idb_path"], str)


def test_create_workspace_rejects_existing_non_empty_directory(tmp_path):
    workspace_dir = tmp_path / "workspace"
    (workspace_dir / "home").mkdir(parents=True)
    (workspace_dir / "home" / "parameters.json").write_text("{}")

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
            "start_step": "Fanout",
            "end_step": "DRC",
            "steps": ["Fanout", "Placement", "CTS", "legal", "Route", "DRC"],
        },
    )

    assert workspace is not None
    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [step["name"] for step in flow_data["steps"]] == [
        "fixFanout",
        "place",
        "CTS",
        "legalization",
        "route",
        "drc",
    ]
    assert [step["tool"] for step in flow_data["steps"]] == [
        "ecc",
        "dreamplace",
        "ecc",
        "dreamplace",
        "ecc",
        "ecc",
    ]
    assert all(step["state"] == "Unstart" for step in flow_data["steps"])
    assert all(step["runtime"] == "" for step in flow_data["steps"])
    assert all(step["peak memory (mb)"] == 0 for step in flow_data["steps"])


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
            "start_step": "fixFanout",
            "end_step": "Harden",
        },
    )

    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [step["name"] for step in flow_data["steps"]] == [
        "fixFanout",
        "place",
        "CTS",
        "legalization",
        "route",
        "drc",
        "filler",
        "RCX",
        "sta",
        "Harden",
    ]


def test_create_workspace_from_step_output_copies_only_origin_inputs_and_rebuilds_flow(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    source_workspace = tmp_path / "source"
    floorplan_output = source_workspace / "Floorplan_ecc" / "output"
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
            "start_step": "fixFanout",
            "end_step": "legalization",
        },
    )

    assert workspace is not None
    assert (workspace_dir / "origin" / "gcd_Floorplan.def.gz").read_text() == "def from floorplan\n"
    assert "module gcd" in (workspace_dir / "origin" / "gcd_Floorplan.v.gz").read_text()
    assert (workspace_dir / "origin" / "gcd.sdc").read_text() == sdc_path.read_text()
    assert not (workspace_dir / "Floorplan_ecc").exists()
    assert not (workspace_dir / "legalization_dreamplace").exists()

    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [step["name"] for step in flow_data["steps"]] == [
        "fixFanout",
        "place",
        "CTS",
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
            "start_step": "CTS",
            "end_step": "CTS",
        },
    )

    from chipcompiler.runtime.workspace_api import build_flow_for_workspace

    build_flow_for_workspace(workspace)

    step_dir = workspace_dir / "CTS_ecc"
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
    assert flow_items["flow.route.completed"]["state"] == "failed"
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
    assert loaded.directory == workspace_dir.resolve()
    assert loaded.design.origin_verilog == workspace_dir.resolve() / "origin" / "gcd.v"
    assert loaded.design.origin_def == workspace_dir.resolve() / "origin" / "gcd.def"
    assert loaded.flow.path == workspace_dir.resolve() / "home" / "flow.json"
    assert loaded.parameters.path == workspace_dir.resolve() / "home" / "parameters.json"
    assert loaded.home.path == workspace_dir.resolve() / "home" / "home.json"
    assert all(isinstance(path, Path) for path in loaded.config.values())


def test_build_workspace_config_paths_returns_path_objects(tmp_path):
    workspace = Workspace(directory=tmp_path / "workspace")

    paths = build_workspace_config_paths(workspace)

    assert paths["dir"] == tmp_path / "workspace" / "config"
    assert paths["flow"] == tmp_path / "workspace" / "config" / "flow_config.json"
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

    assert data_api.workspace_config_path(str(workspace_dir), "flow") == (
        workspace_dir / "config" / "flow_config.json"
    )
    assert data_api.workspace_config_path(workspace_dir, StepEnum.PLACEMENT.value) == (
        workspace_dir / "config" / "pl_default_config.json"
    )
    assert data_api.workspace_config_path(workspace_dir, "unknown") is None


def test_step_config_keys_return_workspace_config_keys():
    assert data_api.step_config_keys("CTS", "ecc") == ("flow", "db", StepEnum.CTS.value)
    assert data_api.step_config_keys("place", "ecc") == (
        "flow",
        "db",
        StepEnum.PLACEMENT.value,
    )
    assert data_api.step_config_keys(StepEnum.PLACEMENT, "ecc") == (
        "flow",
        "db",
        StepEnum.PLACEMENT.value,
    )
    assert data_api.step_config_keys("legalization", "ecc") == (
        "flow",
        "db",
        StepEnum.PLACEMENT.value,
    )
    assert data_api.step_config_keys("filler", "ecc") == (
        "flow",
        "db",
        StepEnum.PLACEMENT.value,
    )
    assert data_api.step_config_keys("sta", "ecc") == (
        "flow",
        "db",
        StepEnum.RCX.value,
        StepEnum.STA.value,
    )
    assert data_api.step_config_keys("place", "dreamplace") == ("dreamplace",)
    assert data_api.step_config_keys("legalization", "dreamplace") == ("dreamplace",)
    assert data_api.step_config_keys("synthesis", "yosys") == ()
    assert data_api.step_config_keys("place", None) == ()


def test_step_config_keys_accept_exact_internal_step_names_only():
    cases = [
        (StepEnum.FLOORPLAN.value, StepEnum.FLOORPLAN.value),
        (StepEnum.NETLIST_OPT.value, StepEnum.NETLIST_OPT.value),
        (StepEnum.PLACEMENT.value, StepEnum.PLACEMENT.value),
        (StepEnum.ROUTING.value, StepEnum.ROUTING.value),
        (StepEnum.TIMING_OPT_DRV.value, StepEnum.TIMING_OPT_DRV.value),
        (StepEnum.TIMING_OPT_HOLD.value, StepEnum.TIMING_OPT_HOLD.value),
        (StepEnum.TIMING_OPT_SETUP.value, StepEnum.TIMING_OPT_SETUP.value),
        (StepEnum.RCX.value, StepEnum.RCX.value),
        ("sta", StepEnum.STA.value),
    ]

    for token, config_key in cases:
        keys = data_api.step_config_keys(token, "ecc")
        assert keys[:2] == ("flow", "db")
        assert config_key in keys

    for cli_token in (
        "floorplan",
        "fixfanout",
        "placement",
        "routing",
        "optdrv",
        "opthold",
        "optsetup",
        "cts",
        "rcx",
    ):
        assert data_api.step_config_keys(cli_token, "ecc") == ()

    assert data_api.step_config_keys("place", "ECC") == ()
    assert data_api.step_config_keys("place", "DreamPlace") == ()


def test_step_config_paths_return_expected_and_existing_paths(tmp_path):
    workspace_dir = tmp_path / "workspace"
    config_dir = workspace_dir / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "flow_config.json").write_text("{}")
    (config_dir / "cts_default_config.json").write_text("{}")

    assert data_api.step_config_paths(workspace_dir, "CTS", "ecc") == (
        config_dir / "flow_config.json",
        config_dir / "db_default_config.json",
        config_dir / "cts_default_config.json",
    )
    assert data_api.step_config_paths(workspace_dir, "CTS", "ecc", existing_only=True) == (
        config_dir / "flow_config.json",
        config_dir / "cts_default_config.json",
    )
    assert data_api.step_config_paths(str(workspace_dir), "place", "dreamplace") == (
        config_dir / "dreamplace.json",
    )
    assert data_api.step_config_paths(workspace_dir, "place", "ECC") == ()
    assert data_api.step_config_paths(workspace_dir, "synthesis", "yosys") == ()


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

    assert not hasattr(data_api, "_flag_to_int")
    assert "_flag_to_int" not in data_api.__all__
    assert hasattr(workspace_data, "_flag_to_int")

    assert hasattr(workspace_data, "_WORKSPACE_CONFIG_FILENAMES")
    assert hasattr(workspace_data, "_STEP_CONFIG_KEYS")
    assert all(
        isinstance(step, StepEnum) and isinstance(tool, str)
        for step, tool in workspace_data._STEP_CONFIG_KEYS
    )

    step_source = Path("chipcompiler/data/step.py").read_text()
    assert "STEP_CONFIG" not in step_source
    assert "WORKSPACE_CONFIG" not in step_source


def test_workspace_data_does_not_import_cli_step_normalization():
    source = Path("chipcompiler/data/workspace.py").read_text()

    assert "normalize_step_name" not in source
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
    resolved_root = pdk_root.resolve()
    assert workspace.pdk.root == resolved_root
    assert workspace.parameters.data.get("PDK Root") == str(resolved_root)

    parameters_data = json.loads((workspace_dir / "home" / "parameters.json").read_text())
    assert parameters_data.get("PDK Root") == str(resolved_root)


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
    resolved_root = pdk_root.resolve()
    assert loaded.pdk.root == resolved_root
    assert loaded.parameters.data.get("PDK Root") == str(resolved_root)
    assert all(path.is_relative_to(resolved_root) for path in loaded.pdk.libs)


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
    parameter_path = workspace_dir / "home" / "parameters.json"
    params = json_read(parameter_path)
    params["Max fanout"] = 88
    params["Global right padding"] = 13
    json_write(parameter_path, params)

    init_workspace_config(workspace)

    fixfanout = json_read(workspace.config["fixFanout"])
    placement = json_read(workspace.config["place"])
    assert fixfanout["max_fanout"] == 88
    assert placement["PL"]["GP"]["global_right_padding"] == 13


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
    parameter_path = workspace_dir / "home" / "parameters.json"
    params = json_read(parameter_path)
    params["Max fanout"] = 91
    params["Global right padding"] = 17
    params["Bottom layer"] = "MET3"
    params["Top layer"] = "MET6"
    params["Target density"] = 0.42
    params["Target overflow"] = 0.07
    params["Cell padding x"] = 444
    params["Routability opt flag"] = 0
    json_write(parameter_path, params)

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


def test_refresh_workspace_config_preserves_routability_flag_string_coercion(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    for index, (raw_value, expected) in enumerate(ROUTABILITY_FLAG_STRING_CASES):
        workspace_dir, workspace = _create_loaded_ics55_workspace(
            tmp_path,
            f"workspace_param_flag_{index}",
            minimal_ics55_pdk_factory,
            default_ics55_parameters,
        )
        parameter_path = workspace_dir / "home" / "parameters.json"
        params = json_read(parameter_path)
        params["Routability opt flag"] = raw_value
        json_write(parameter_path, params)

        refresh_workspace_config(workspace)

        dreamplace = json_read(workspace.config["dreamplace"])
        assert dreamplace["routability_opt_flag"] == expected


def test_refresh_workspace_config_preserves_nested_dreamplace_override_precedence(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    workspace_dir, workspace = _create_loaded_ics55_workspace(
        tmp_path,
        "workspace_dreamplace_precedence",
        minimal_ics55_pdk_factory,
        default_ics55_parameters,
    )
    parameter_path = workspace_dir / "home" / "parameters.json"
    params = json_read(parameter_path)
    params["Target density"] = 0.25
    params["Routability opt flag"] = "true"
    params["DreamPlace"] = {
        "target_density": 0.88,
        "routability_opt_flag": 0,
    }
    json_write(parameter_path, params)

    refresh_workspace_config(workspace)

    dreamplace = json_read(workspace.config["dreamplace"])
    assert dreamplace["target_density"] == 0.88
    assert dreamplace["routability_opt_flag"] == 0


def test_sync_workspace_config_to_parameters_updates_routing_layers_and_refreshes_peers(
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
    routing = json_read(workspace.config["route"])
    routing["RT"]["-bottom_routing_layer"] = "MET4"
    routing["RT"]["-top_routing_layer"] = "MET7"
    json_write(workspace.config["route"], routing)

    assert sync_workspace_config_to_parameters(workspace, workspace.config["route"]) is True
    refresh_workspace_config(workspace)

    params = json_read(workspace_dir / "home" / "parameters.json")
    db = json_read(workspace.config["db"])
    assert params["Bottom layer"] == "MET4"
    assert params["Top layer"] == "MET7"
    assert db["LayerSettings"]["routing_layer_1st"] == "MET4"


def test_sync_workspace_config_to_parameters_preserves_routability_flag_string_coercion(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    for index, (raw_value, expected) in enumerate(ROUTABILITY_FLAG_STRING_CASES):
        workspace_dir, workspace = _create_loaded_ics55_workspace(
            tmp_path,
            f"workspace_config_flag_{index}",
            minimal_ics55_pdk_factory,
            default_ics55_parameters,
        )
        parameter_path = workspace_dir / "home" / "parameters.json"
        params = json_read(parameter_path)
        params["Routability opt flag"] = -1
        json_write(parameter_path, params)

        dreamplace = json_read(workspace.config["dreamplace"])
        dreamplace["routability_opt_flag"] = raw_value
        json_write(workspace.config["dreamplace"], dreamplace)

        assert sync_workspace_config_to_parameters(workspace, workspace.config["dreamplace"]) is True

        params = json_read(parameter_path)
        assert params["Routability opt flag"] == expected


def test_sync_workspace_config_to_parameters_ignores_unmanaged_fields(
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
    cts = json_read(workspace.config["CTS"])
    cts["skew_bound"] = 0.12
    json_write(workspace.config["CTS"], cts)
    parameter_path = workspace_dir / "home" / "parameters.json"
    before = json_read(parameter_path)

    assert sync_workspace_config_to_parameters(workspace, workspace.config["CTS"]) is False

    after = json_read(parameter_path)
    assert after == before


def test_prepare_workspace_for_rerun_deletes_old_artifacts_and_resets_home_state(
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
    home = json_read(home_path)
    home["layout"] = str(step_dir / "output" / "gcd_floorplan.png")
    home["metrics"] = {"instances dist.": str(step_dir / "feature" / "floorplan.db.inst_dist.png")}
    home["monitor"] = {
        "step": ["Floorplan - init"],
        "memory": ["1"],
        "runtime": ["2"],
        "instance": [3],
        "frequency": [4.0],
    }
    json_write(home_path, home)

    flow_path = workspace_dir / "home" / "flow.json"
    json_write(
        flow_path,
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
        checklist_path,
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
    assert (
        reset_parameters["Core"]["Utilitization"] == parameters_before_json["Core"]["Utilitization"]
    )
    assert reset_parameters["Core"]["Margin"] == parameters_before_json["Core"]["Margin"]
    assert (
        reset_parameters["Core"]["Aspect ratio"] == parameters_before_json["Core"]["Aspect ratio"]
    )
    assert reset_parameters["Die"]["Size"] == []
    assert reset_parameters["Die"]["Area"] == 0
    assert reset_parameters["Core"]["Size"] == []
    assert reset_parameters["Core"]["Area"] == 0
    assert reset_parameters["Core"]["Bounding box"] == ""

    reset_home = json_read(home_path)
    assert reset_home["parameters"] == str(workspace_dir / "home" / "parameters.json")
    assert reset_home["flow"] == str(flow_path)
    assert reset_home["checklist"] == str(checklist_path)
    assert reset_home["layout"] == ""
    assert reset_home["metrics"] == {}
    assert reset_home["monitor"]["step"] == []

    reset_flow = json_read(flow_path)
    assert reset_flow["steps"][0]["state"] == "Unstart"
    assert reset_flow["steps"][0]["runtime"] == ""
    assert reset_flow["steps"][0]["peak memory (mb)"] == 0

    assert json_read(checklist_path) == {
        "path": str(checklist_path),
        "checklist": [],
    }
    assert engine_flow.engine_db is None
    assert engine_flow.clear_calls == 1
    assert engine_flow.create_calls == 1


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
    resolved_root = pdk_root.resolve()
    assert workspace.pdk.root == resolved_root
    assert workspace.parameters.data.get("PDK Root") == str(resolved_root)

    parameters_data = json.loads((workspace_dir / "home" / "parameters.json").read_text())
    assert parameters_data.get("PDK Root") == str(resolved_root)


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
    resolved_root = pdk_root.resolve()
    assert loaded.pdk.root == resolved_root
    assert loaded.parameters.data.get("PDK Root") == str(resolved_root)
    assert all(path.is_relative_to(resolved_root) for path in loaded.pdk.libs)
