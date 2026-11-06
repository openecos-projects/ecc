"""Runtime selection of workspace-owned pre/post-CTS constraints."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from chipcompiler.data import PDK, OriginDesign, Parameters, StepEnum, Workspace
from chipcompiler.data.handshake import StepInputs, StepRequest, UpstreamResponse, write_request
from chipcompiler.data.types import AnalysisData
from chipcompiler.data.workspace.timing_constraints import generate_timing_scripts, timing_scenarios
from chipcompiler.tools.ecc import runner
from chipcompiler.tools.ecc.builder import build_step, build_step_space
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.timing_constraints import prepare_timing_context, step_tcl_path


@pytest.fixture
def timing_workspace(tmp_path):
    template = Path(runner.__file__).parent / "configs" / "sta_ecc.json"
    config = json.loads(template.read_text())
    for library in config["liberty"]:
        library["path"] = [str(tmp_path / Path(path).name) for path in library["path"]]
        for path in library["path"]:
            Path(path).touch()
    config_path = tmp_path / "config" / "sta_ecc.json"
    config_path.parent.mkdir()
    config_path.write_text(json.dumps(config))
    origin = tmp_path / "origin"
    origin.mkdir()
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
        pdk=PDK(libs=[Path(path) for path in config["liberty"][0]["path"]]),
        config={StepEnum.STA.value: config_path},
        parameters=Parameters(data={"clock": "clk", "frequency_max": 100}),
    )
    generate_timing_scripts(workspace)
    return workspace


@pytest.fixture
def native_module():
    module = Mock(spec=ECCToolsModule)

    def export(json_path):
        json_path.write_text(json.dumps({"Instances": {"iopads": {"num": 0}}}))
        return True

    module.feature_sammry.side_effect = export
    return module


@pytest.mark.parametrize("io_cells", [0, 2])
def test_stage_selection_reuses_resolved_constraints(timing_workspace, io_cells):
    workspace = timing_workspace
    module = Mock(spec=ECCToolsModule)

    def export(json_path):
        json_path.write_text(json.dumps({"Instances": {"iopads": {"num": io_cells}}}))
        return True

    module.feature_sammry.side_effect = export
    generate_timing_scripts(workspace, has_io_cells=io_cells > 0)
    files = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (workspace.directory / "origin").rglob("*.tcl")
    }
    for name, phase_dir in (
        (StepEnum.SYNTHESIS, "pre_CTS"),
        (StepEnum.PRE_FLOORPLAN, "pre_CTS"),
        (StepEnum.CTS, "pre_CTS"),
        (StepEnum.ROUTING, "post_CTS"),
        (StepEnum.POWER_ANALYSIS, "post_CTS"),
        (StepEnum.HARDEN, "post_CTS"),
    ):
        step = build_step(workspace, name.value, input_def=None, input_verilog=None)
        build_step_space(step)
        prepare_timing_context(workspace, step, module)
        assert (
            step_tcl_path(workspace, step)
            == workspace.directory / "origin" / phase_dir / "TYP_25_TYPICAL.tcl"
        )
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files} == files
    module.close.assert_not_called()


@pytest.mark.parametrize("io_cells", [0, 2])
def test_native_preparation_resolves_current_io_branch(timing_workspace, io_cells):
    workspace = timing_workspace
    module = Mock(spec=ECCToolsModule)

    def export(json_path):
        json_path.write_text(json.dumps({"Instances": {"iopads": {"num": io_cells}}}))
        return True

    module.feature_sammry.side_effect = export
    step = build_step(workspace, StepEnum.CTS.value, input_def=None, input_verilog=None)
    build_step_space(step)
    generate_timing_scripts(workspace, has_io_cells=not bool(io_cells))
    prepare_timing_context(workspace, step, module)
    actual = {path: path.read_bytes() for path in (workspace.directory / "origin").rglob("*.tcl")}
    generate_timing_scripts(workspace, has_io_cells=bool(io_cells))
    assert actual == {path: path.read_bytes() for path in actual}


def test_native_probe_is_closed_and_failed_export_never_reuses_old_count(
    timing_workspace, native_module, monkeypatch
):
    step = build_step(
        timing_workspace, StepEnum.PRE_FLOORPLAN.value, input_def=None, input_verilog=None
    )
    build_step_space(step)
    monkeypatch.setattr(runner, "create_db_engine", lambda *_args: native_module)
    prepare_timing_context(timing_workspace, step)
    native_module.close.assert_called_once()
    native_module.feature_sammry.side_effect = None
    native_module.feature_sammry.return_value = False
    with pytest.raises(RuntimeError, match="Cannot export current iDB IO-cell count"):
        prepare_timing_context(timing_workspace, step)
    assert native_module.close.call_count == 2


@pytest.mark.parametrize("suffix", [".sdc", ".tcl"])
@pytest.mark.parametrize(
    ("step_name", "phase"),
    [
        (StepEnum.PREPLACE, "pre_CTS"),
        (StepEnum.CTS, "pre_CTS"),
        (StepEnum.ROUTING, "post_CTS"),
        (StepEnum.STA, "post_CTS"),
        (StepEnum.POWER_ANALYSIS, "post_CTS"),
    ],
)
def test_custom_constraints_select_phase_without_native_probe(
    timing_workspace, native_module, suffix, step_name, phase
):
    workspace = timing_workspace
    custom = workspace.directory / f"custom{suffix}"
    contents = b"# custom \xff\ncreate_clock -period 5 [get_ports fast_clk]\n"
    custom.write_bytes(contents)
    workspace.pdk.sdc = custom
    workspace.config.clear()
    step = build_step(workspace, step_name.value, input_def=None, input_verilog=None)
    files = {path: path.read_bytes() for path in (workspace.directory / "origin").rglob("*.tcl")}
    generate_timing_scripts(workspace)
    prepare_timing_context(workspace, step, native_module)
    expected = workspace.directory / "origin" / phase / f"{custom.name}.ecc.tcl"
    assert step_tcl_path(workspace, step) == expected
    assert expected.is_file()
    assert custom.read_bytes() == contents
    assert {path: path.read_bytes() for path in files} == files
    assert native_module.mock_calls == []


def test_final_sta_selects_each_actual_corner(timing_workspace):
    step = build_step(timing_workspace, StepEnum.STA.value, input_def=None, input_verilog=None)
    for scenario in timing_scenarios(timing_workspace):
        path = step_tcl_path(timing_workspace, step, corner=scenario.corner, rc=scenario.rc)
        assert path is not None
        assert path.parent == timing_workspace.directory / "origin/post_CTS"
        assert f'set corner "{scenario.corner}"' in path.read_text()
        assert f'set rc_para "{scenario.rc}"' in path.read_text()


def test_custom_sta_selection_preserves_typical_consumers_and_custom_scenarios(timing_workspace):
    workspace = timing_workspace
    config_path = workspace.config["sta"]
    config = json.loads(config_path.read_text())
    max_library = next(item for item in config["liberty"] if item["corner"] == "MAX")
    config["liberty"] = [{**max_library, "temperature": 85}]
    config["signoff"] = [{"MAX": ["Cworst", "RCbest"]}]
    config_path.write_text(json.dumps(config))
    config_before = config_path.read_bytes()
    generate_timing_scripts(workspace)

    step = build_step(workspace, StepEnum.STA.value, input_def=None, input_verilog=None)
    assert step.directory is not None
    # STA reads its parasitics from the RCX step its req.json names.
    write_request(
        StepRequest(
            workspace_directory=workspace.directory,
            step=StepEnum.STA.value,
            tool="ecc",
            step_directory=step.directory.name,
            attempt_id="attempt-sta",
            inputs=StepInputs(),
            design_source=None,
            upstream={AnalysisData.PARASITICS: UpstreamResponse("RCX_ecc", None)},
            final_step=False,
            layout_image=False,
        )
    )
    items = runner.collect_sta_signoff_items(workspace, step)
    assert [(item["corner"], item["temperature"], item["rcx_corner"]) for item in items] == [
        ("MAX", 85, "Cworst"),
        ("MAX", 85, "RCbest"),
    ]
    paths = [
        step_tcl_path(workspace, step, corner=item["corner"], rc=item["rcx_corner"])
        for item in items
    ]
    assert paths == [
        workspace.directory / "origin/post_CTS/MAX_85_Cworst.tcl",
        workspace.directory / "origin/post_CTS/MAX_85_RCbest.tcl",
    ]
    assert all(path is not None and path.is_file() for path in paths)

    for name, phase in ((StepEnum.PREPLACE, "pre_CTS"), (StepEnum.HARDEN, "post_CTS")):
        step = build_step(workspace, name.value, input_def=None, input_verilog=None)
        typical = step_tcl_path(workspace, step)
        assert typical == workspace.directory / "origin" / phase / "TYP_25_TYPICAL.tcl"
        assert typical is not None and typical.is_file()
    assert config_path.read_bytes() == config_before


def test_harden_uses_typical_signoff_item_for_lib_spef_and_sdc(
    timing_workspace, native_module, monkeypatch
):
    workspace = timing_workspace
    config_path = workspace.config[StepEnum.STA.value]
    config = json.loads(config_path.read_text())
    config["signoff"] = [{"MAX": ["Cworst"]}, {"TYP": ["TYPICAL"]}]
    config_path.write_text(json.dumps(config))
    workspace.pdk.mapping_file = workspace.directory / "layer.map"
    step = build_step(workspace, StepEnum.HARDEN.value, input_def=None, input_verilog=None)
    build_step_space(step)
    monkeypatch.setattr(runner, "EccSubFlow", Mock())
    monkeypatch.setattr(runner, "get_eda_instance", lambda **_: native_module)
    monkeypatch.setattr(runner, "run_analysis", lambda **_: None)

    assert runner.run_harden(workspace, step) is True

    typical = next(item for item in config["liberty"] if item["corner"] == "TYP")
    timing_model = native_module.write_timing_model.call_args.kwargs
    assert timing_model["lib_paths"] == typical["path"]
    assert timing_model["spef_path"] == str(
        workspace.directory / "RCX_ecc" / "output" / "gcd_TYPICAL_25C.spef"
    )
    assert timing_model["sdc_path"] == (
        workspace.directory / "origin" / "post_CTS" / "TYP_25_TYPICAL.tcl"
    )


@pytest.mark.parametrize("custom", [False, True])
def test_cts_receives_pre_cts_constraints(timing_workspace, native_module, monkeypatch, custom):
    workspace = timing_workspace
    filename = "TYP_25_TYPICAL.tcl"
    if custom:
        workspace.pdk.sdc = workspace.directory / "user.sdc"
        workspace.pdk.sdc.write_text(
            "create_clock -period 10 [get_ports clk]\nset_propagated_clock [all_clocks]\n"
        )
        filename = "user.sdc.ecc.tcl"
    step = build_step(workspace, StepEnum.CTS.value, input_def=None, input_verilog=None)
    build_step_space(step)
    native_module.run_cts.return_value = False
    monkeypatch.setattr(runner, "EccSubFlow", Mock())
    assert runner.run_cts(workspace, step, native_module) is False
    native_module.update_sta_data_config.assert_called_once_with(
        db_config="",
        output_dir=step.data.dir,
        lib_paths=workspace.pdk.libs,
        sdc_path=workspace.directory / "origin/pre_CTS" / filename,
    )


def test_post_synthesis_sta_receives_pre_cts_typical(timing_workspace, native_module):
    workspace = timing_workspace
    step = build_step(workspace, StepEnum.SYNTHESIS.value, input_def=None, input_verilog=None)
    build_step_space(step)
    assert step.output.verilog is not None
    step.output.verilog.write_text("module gcd; endmodule\n")
    assert runner.run_sta_without_spef(workspace, step, native_module) is True
    assert (
        native_module.run_timing.call_args.kwargs["sdc_path"]
        == workspace.directory / "origin/pre_CTS/TYP_25_TYPICAL.tcl"
    )
