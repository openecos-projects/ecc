"""Floorplan inputs stay stable when native geometry is saved between stages."""

from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from chipcompiler.data import StepEnum, create_workspace
from chipcompiler.data.parameter import get_design_parameters, load_parameter, save_parameter
from chipcompiler.data.workspace import refresh_workspace_config
from chipcompiler.tools.ecc import ECCToolsModule
from chipcompiler.tools.ecc import runner as ecc_runner
from chipcompiler.tools.ecc.builder import build_step, build_step_config, build_step_space
from chipcompiler.utility import json_read, json_write


@pytest.fixture
def floorplan_workspace(tmp_path, minimal_ics55_pdk_factory):
    rtl = tmp_path / "gcd.v"
    rtl.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    parameters = get_design_parameters("ics55", "gcd").data
    parameters["run_analysis"] = False
    workspace = create_workspace(
        directory=str(tmp_path / "workspace"),
        origin_def="",
        origin_verilog=str(rtl),
        pdk="ics55",
        parameters=parameters,
        pdk_root=str(minimal_ics55_pdk_factory(tmp_path / "pdk")),
    )
    assert workspace is not None
    return workspace


@pytest.fixture
def native_geometry(monkeypatch):
    # Site/row alignment makes this realized die non-square even when the
    # requested aspect ratio is 1. It must remain an output, not a new input.
    layout = {
        "die_bounding_width": 1487.2,
        "die_bounding_height": 1488.0,
        "die_area": 2212953.6,
        "core_bounding_width": 1483.2,
        "core_bounding_height": 1484.0,
        "core_area": 2201068.8,
    }
    module = Mock(spec=ECCToolsModule)
    module.feature_sammry.side_effect = lambda json_path: json_write(
        json_path, {"Design Layout": layout}
    )

    def save_geometry(output_dir, **_kwargs):
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "geometry.manifest").write_text("schema=ecc.geometry.v1\n")
        return True

    module.geometry_snapshot_save.side_effect = save_geometry
    monkeypatch.setattr(ecc_runner, "get_eda_instance", lambda **_kwargs: module)
    return module, layout


@pytest.mark.parametrize("requested_ratio", [1.0, 1.25])
@pytest.mark.parametrize("explicit_size", [False, True], ids=["die-util", "die-size"])
def test_floorplan_stages_preserve_requested_geometry(
    floorplan_workspace, native_geometry, requested_ratio, explicit_size
):
    workspace = floorplan_workspace
    module, layout = native_geometry
    workspace.parameters.data["core"].update(
        {"aspect_ratio": requested_ratio, "utilitization": 0.4, "margin": [2, 2]}
    )
    if explicit_size:
        workspace.parameters.data["die"]["size"] = [1487.2, 1488.0]
    assert save_parameter(workspace.parameters)
    refresh_workspace_config(workspace)
    expected_parameters = deepcopy(workspace.parameters.data)
    expected_parameters["core"].update(
        {
            "size": [1483.2, 1484.0],
            "area": 2201068.8,
            "bounding_box": "(2 , 2) (1485.2 , 1486.0)",
        }
    )
    if explicit_size:
        expected_parameters["die"]["area"] = layout["die_area"]

    pre = build_step(workspace, StepEnum.PRE_FLOORPLAN.value, None, None)
    build_step_space(pre)
    build_step_config(workspace, pre)
    assert ecc_runner.run_pre_floorplan(workspace, pre)
    floorplan_path = workspace.config[StepEnum.FLOORPLAN.value]
    simple_config = json_read(floorplan_path.with_stem(f"{floorplan_path.stem}_simple"))
    assert workspace.parameters.data == expected_parameters
    assert load_parameter(workspace.parameters.path).data == expected_parameters

    macro = build_step(workspace, StepEnum.MACRO_PLACEMENT.value, None, None, tool="dreamplace")
    build_step_space(macro)
    assert ecc_runner.save_data(workspace, macro, module, feature_step=False)
    assert load_parameter(workspace.parameters.path).data == expected_parameters

    post = build_step(workspace, StepEnum.POST_FLOORPLAN.value, None, None)
    build_step_space(post)
    build_step_config(workspace, post)
    assert ecc_runner.run_post_floorplan(workspace, post)
    expected_config = deepcopy(simple_config)
    expected_config["ifp"]["temp_directory_path"] = str(post.data.workdir_for(post.name))
    expected_config["macro_placer"].update(
        {"mode": "file", "file_path": str(workspace.config["macro_location"])}
    )
    assert json_read(floorplan_path) == expected_config
    assert workspace.parameters.data == expected_parameters
    assert load_parameter(workspace.parameters.path).data == expected_parameters
    for step in (pre, macro, post):
        assert step.feature.db is not None
        assert json_read(step.feature.db) == {"Design Layout": layout}

    # A later config refresh/rerun must consume the same requested geometry.
    build_step_config(workspace, pre)
    assert ecc_runner.run_pre_floorplan(workspace, pre)
    assert json_read(floorplan_path.with_stem(f"{floorplan_path.stem}_simple")) == simple_config
