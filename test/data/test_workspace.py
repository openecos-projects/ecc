import json
from copy import deepcopy
from pathlib import Path

import pytest

import chipcompiler.data as data_api
import chipcompiler.data.workspace as workspace_data
from chipcompiler.data import (
    StepEnum,
    create_workspace,
    load_workspace,
)
from chipcompiler.data.workspace import (
    Flow,
    Workspace,
    build_workspace_config_paths,
    init_workspace_config,
    prepare_workspace_for_rerun,
    refresh_workspace_config,
    sync_workspace_config_to_parameters,
)
from chipcompiler.utility import json_read, json_write

EXPECTED_WORKSPACE_CONFIG_FILENAMES = {
    "db": "db_ecc.json",
    StepEnum.CTS.value: "cts_ecc.json",
    StepEnum.DRC.value: "drc_ecc.json",
    StepEnum.FLOORPLAN.value: "floorplan_ecc.json",
    StepEnum.ROUTING.value: "route_ecc.json",
    StepEnum.FILLER.value: "filler_ecc.json",
    StepEnum.RCX.value: "rcx_ecc.json",
    StepEnum.STA.value: "sta_ecc.json",
    "dreamplace": "dreamplace_ecc.json",
}

ROUTABILITY_FLAG_STRING_CASES = (
    ("true", 1),
    ("false", 0),
    ("2", 2),
    ("maybe", 1),
)


def test_flow_has_step_uses_cached_data_and_path(tmp_path):
    flow = Flow(
        data={
            "steps": [
                {"name": StepEnum.SYNTHESIS.value, "tool": "yosys"},
                {"name": StepEnum.FLOORPLAN.value, "tool": "ecc"},
            ]
        }
    )
    assert flow.has_step(StepEnum.SYNTHESIS)
    assert flow.has_step("Synthesis", "yosys")
    assert not flow.has_step(StepEnum.SYNTHESIS, "ecc")
    assert flow.get_step(StepEnum.FLOORPLAN)["tool"] == "ecc"
    assert flow.get_step(StepEnum.PLACEMENT) is None

    path = tmp_path / "flow.json"
    path.write_text(
        json.dumps({"steps": [{"name": StepEnum.FLOORPLAN.value, "tool": "ecc"}]}),
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
        parameters={**default_ics55_parameters, "max_fanout": 37},
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

    cts = json_read(workspace.config[StepEnum.CTS.value])
    assert cts["max_fanout"] == 37
    assert cts["buffer_type"] == workspace.pdk.buffers


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
            "start_step": "Placement",
            "end_step": "DRC",
            "steps": ["Placement", "CTS", "legal", "Route", "DRC"],
        },
    )

    assert workspace is not None
    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [step["name"] for step in flow_data["steps"]] == [
        "place",
        "CTS",
        "legalization",
        "Timing optimization",
        "route",
        "drc",
    ]
    assert [step["tool"] for step in flow_data["steps"]] == [
        "dreamplace",
        "ecc",
        "dreamplace",
        "sizer",
        "ecc",
        "ecc",
    ]
    assert all(step["state"] == "Unstart" for step in flow_data["steps"])
    assert all(step["runtime"] == "" for step in flow_data["steps"])
    assert all(step["peak memory (mb)"] == 0 for step in flow_data["steps"])


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
            flow_config={"steps": ["Synth", "Place", "CTS"]},
        )

    assert workspace is not None
    # Both stores carry the same contiguous first..last range.
    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [step["name"] for step in flow_data["steps"]] == [
        "Synthesis",
        "Floorplan",
        "place",
        "CTS",
    ]
    assert workspace.parameters.data["_flow"] == {"start": "Synthesis", "end": "CTS"}
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
            "start_step": "Placement",
            "end_step": "Harden",
        },
    )

    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [step["name"] for step in flow_data["steps"]] == [
        "place",
        "CTS",
        "legalization",
        "Timing optimization",
        "route",
        "drc",
        "lvs",
        "filler",
        "postRouteLec",
        "RCX",
        "sta",
        "Harden",
    ]


POST_ROUTE_LEC_STEP_ALIAS_CASES = (
    ["filler", "postRouteLec", "RCX"],
    ["filler", "postlec", "RCX"],
    ["filler", "postroutelec", "RCX"],
    ["filler", "post_route_lec", "RCX"],
    ["filler", "Post-Route-LEC", "RCX"],
)


@pytest.mark.parametrize("steps", POST_ROUTE_LEC_STEP_ALIAS_CASES)
def test_create_workspace_normalizes_post_route_lec_step_aliases(
    steps, tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
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
            "start_step": "filler",
            "end_step": "RCX",
            "steps": steps,
        },
    )

    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [(step["name"], step["tool"]) for step in flow_data["steps"]] == [
        ("filler", "ecc"),
        ("postRouteLec", "yosys_lec"),
        ("RCX", "ecc"),
    ]


def test_create_workspace_normalizes_post_route_lec_boundary_aliases(
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
            "start_step": "postlec",
            "end_step": "post route lec",
        },
    )

    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [(step["name"], step["tool"]) for step in flow_data["steps"]] == [
        ("postRouteLec", "yosys_lec"),
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
            "start_step": "Placement",
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
    assert loaded.parameters.path == workspace_dir.resolve() / "home" / "params.toml"
    assert loaded.home.path == workspace_dir.resolve() / "home" / "home.json"
    assert all(isinstance(path, Path) for path in loaded.config.values())


def test_load_workspace_migrates_legacy_config_filenames(
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

    config_dir = workspace_dir / "config"
    legacy_filenames = workspace_data._LEGACY_WORKSPACE_CONFIG_FILENAMES
    for config_key, legacy_filename in legacy_filenames.items():
        workspace.config[config_key].rename(config_dir / legacy_filename)

    loaded = load_workspace(workspace_dir)

    assert loaded is not None
    for config_key, legacy_filename in legacy_filenames.items():
        assert not (config_dir / legacy_filename).exists()
        assert loaded.config[config_key] == (
            config_dir / EXPECTED_WORKSPACE_CONFIG_FILENAMES[config_key]
        )
        assert loaded.config[config_key].is_file()


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

    assert data_api.workspace_config_path(str(workspace_dir), "db") == (
        workspace_dir / "config" / "db_ecc.json"
    )
    assert data_api.workspace_config_path(workspace_dir, StepEnum.FILLER.value) == (
        workspace_dir / "config" / "filler_ecc.json"
    )
    assert data_api.workspace_config_path(workspace_dir, StepEnum.PLACEMENT.value) is None
    assert data_api.workspace_config_path(workspace_dir, StepEnum.LEGALIZATION.value) is None
    assert data_api.workspace_config_path(workspace_dir, "unknown") is None


def test_step_config_keys_return_workspace_config_keys():
    assert data_api.step_config_keys("CTS", "ecc") == ("db", StepEnum.CTS.value)
    assert data_api.step_config_keys("place", "ecc") == ("db",)
    assert data_api.step_config_keys(StepEnum.PLACEMENT, "ecc") == ("db",)
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
    assert data_api.step_config_keys("place", "dreamplace") == ("dreamplace",)
    assert data_api.step_config_keys("legalization", "dreamplace") == ("dreamplace",)
    assert data_api.step_config_keys("Timing optimization", "sizer") == ("db", "dreamplace")
    assert data_api.step_config_keys(StepEnum.TIMING_OPT, "sizer") == ("db", "dreamplace")
    assert data_api.step_config_keys("synthesis", "yosys") == ()
    assert data_api.step_config_keys("place", None) == ()


def test_step_config_keys_accept_exact_internal_step_names_only():
    cases = [
        (StepEnum.FLOORPLAN.value, StepEnum.FLOORPLAN.value),
        (StepEnum.ROUTING.value, StepEnum.ROUTING.value),
        (StepEnum.RCX.value, StepEnum.RCX.value),
        ("sta", StepEnum.STA.value),
    ]

    for token, config_key in cases:
        keys = data_api.step_config_keys(token, "ecc")
        assert keys[0] == "db"
        assert config_key in keys

    for cli_token in (
        "floorplan",
        "placement",
        "routing",
        "cts",
        "rcx",
    ):
        assert data_api.step_config_keys(cli_token, "ecc") == ()

    assert data_api.step_config_keys("place", "ECC") == ()
    assert data_api.step_config_keys("place", "not-a-tool") == ()


def test_step_config_paths_return_expected_and_existing_paths(tmp_path):
    workspace_dir = tmp_path / "workspace"
    config_dir = workspace_dir / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "cts_ecc.json").write_text("{}")

    assert data_api.step_config_paths(workspace_dir, "CTS", "ecc") == (
        config_dir / "db_ecc.json",
        config_dir / "cts_ecc.json",
    )
    assert data_api.step_config_paths(workspace_dir, "CTS", "ecc", existing_only=True) == (
        config_dir / "cts_ecc.json",
    )
    assert data_api.step_config_paths(str(workspace_dir), "place", "dreamplace") == (
        config_dir / "dreamplace_ecc.json",
    )
    assert data_api.step_config_paths(workspace_dir, "legalization", "dreamplace") == (
        config_dir / "dreamplace_ecc.json",
    )
    assert data_api.step_config_paths(workspace_dir, StepEnum.TIMING_OPT, "sizer") == (
        config_dir / "db_ecc.json",
        config_dir / "dreamplace_ecc.json",
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
    source = Path("chipcompiler/data/workspace/__init__.py").read_text()

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
    parameter_path = workspace_dir / "home" / "params.toml"
    params = _read_parameters(parameter_path)
    params["max_fanout"] = 88
    params["global_right_padding"] = 13
    _write_parameters(parameter_path, params)

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
    parameter_path = workspace_dir / "home" / "params.toml"
    params = _read_parameters(parameter_path)
    params["max_fanout"] = 91
    params["global_right_padding"] = 17
    params["bottom_layer"] = "MET3"
    params["top_layer"] = "MET6"
    params["target_density"] = 0.42
    params["target_overflow"] = 0.07
    params["cell_padding_x"] = 444
    params["routability_opt_flag"] = 0
    _write_parameters(parameter_path, params)

    cts = json_read(workspace.config[StepEnum.CTS.value])
    cts["skew_bound"] = "0.13"
    json_write(workspace.config[StepEnum.CTS.value], cts)

    refresh_workspace_config(workspace)

    filler = json_read(workspace.config["filler"])
    db = json_read(workspace.config["db"])
    floorplan = json_read(workspace.config[StepEnum.FLOORPLAN.value])
    routing = json_read(workspace.config["route"])
    cts = json_read(workspace.config[StepEnum.CTS.value])
    dreamplace = json_read(workspace.config["dreamplace"])

    assert cts["max_fanout"] == 91
    assert cts["buffer_type"] == workspace.pdk.buffers
    assert cts["skew_bound"] == "0.13"
    assert filler == {"-min_filler_width": 1}
    assert db["LayerSettings"]["routing_layer_1st"] == "MET3"
    assert routing["RT"]["-bottom_routing_layer"] == "MET3"
    assert routing["RT"]["-top_routing_layer"] == "MET6"
    assert dreamplace["target_density"] == 0.42
    assert dreamplace["stop_overflow"] == 0.07
    assert dreamplace["cell_padding_x"] == 444
    assert dreamplace["routability_opt_flag"] == 0
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
    assert floorplan["io_placer"] == {"io_layer_list": ["MET3", "MET4"]}


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
        parameter_path = workspace_dir / "home" / "params.toml"
        params = _read_parameters(parameter_path)
        params["routability_opt_flag"] = raw_value
        _write_parameters(parameter_path, params)

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

    params = _read_parameters(workspace_dir / "home" / "params.toml")
    db = json_read(workspace.config["db"])
    assert params["bottom_layer"] == "MET4"
    assert params["top_layer"] == "MET7"
    assert db["LayerSettings"]["routing_layer_1st"] == "MET4"


def test_sync_workspace_config_to_parameters_propagates_cts_max_fanout(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    workspace_dir, workspace = _create_loaded_ics55_workspace(
        tmp_path,
        "workspace_cts_max_fanout",
        minimal_ics55_pdk_factory,
        default_ics55_parameters,
    )
    cts_path = workspace.config[StepEnum.CTS.value]
    cts = json_read(cts_path)
    cts["max_fanout"] = 48
    json_write(cts_path, cts)

    assert sync_workspace_config_to_parameters(workspace, cts_path) is True
    refresh_workspace_config(workspace)

    from chipcompiler.data.parameter import load_parameter

    parameters = load_parameter(workspace_dir / "home" / "params.toml")
    cts = json_read(cts_path)
    assert parameters.data["max_fanout"] == 48
    assert cts["max_fanout"] == 48


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
        parameter_path = workspace_dir / "home" / "params.toml"
        params = _read_parameters(parameter_path)
        params["routability_opt_flag"] = -1
        _write_parameters(parameter_path, params)

        dreamplace = json_read(workspace.config["dreamplace"])
        dreamplace["routability_opt_flag"] = raw_value
        json_write(workspace.config["dreamplace"], dreamplace)

        assert (
            sync_workspace_config_to_parameters(workspace, workspace.config["dreamplace"]) is True
        )

        params = _read_parameters(parameter_path)
        assert params["routability_opt_flag"] == expected


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
    parameter_path = workspace_dir / "home" / "params.toml"
    before = _read_parameters(parameter_path)

    assert sync_workspace_config_to_parameters(workspace, workspace.config["CTS"]) is False

    after = _read_parameters(parameter_path)
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

    home_path = workspace_dir / "home" / "home.json"
    home = json_read(home_path)
    home["layout"] = str(step_dir / "output" / "gcd_floorplan.png")
    home["metrics"] = {"instances dist.": str(step_dir / "feature" / "floorplan.db.inst_dist.png")}
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
                    "type": "area",
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

    reset_home = json_read(home_path)
    assert reset_home["parameters"] == str(workspace_dir / "home" / "params.toml")
    assert reset_home["flow"] == str(flow_path)
    assert reset_home["checklist"] == str(checklist_path)
    assert reset_home["layout"] == ""
    assert reset_home["metrics"] == {}

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
    assert json_read(home_path)["parameters"] == str(parameter_path)
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
    assert workspace.pdk.dont_use == original_dont_use


def test_workspace_pdk_overrides_not_persisted_on_reload(
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
    assert workspace.pdk.dont_use == ["ICG*"]

    loaded = load_workspace(str(workspace_dir))

    from chipcompiler.data.pdk import get_pdk

    base_pdk = get_pdk("ics55", pdk_root=pdk_root)
    assert loaded.pdk.dont_use == base_pdk.dont_use


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
