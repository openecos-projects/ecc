"""STA library paths survive workspace and per-step override replay."""

from copy import deepcopy

import pytest

from chipcompiler.data import StepEnum, create_workspace
from chipcompiler.data.workspace import refresh_workspace_config, update_step_config
from chipcompiler.tools.ecc.builder import build_step
from chipcompiler.utility import json_read


@pytest.mark.parametrize("rc_corner", [None, "Cworst"])
def test_sta_refresh_preserves_declared_absolute_and_relative_paths(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters, gcd_rtl_file, rc_corner
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "pdk")
    external = pdk_root / "macro libraries" / "sram.lib"
    external.parent.mkdir()
    external.write_text("library(sram) {}\n")
    absolute_internal = pdk_root / "IP" / "absolute.lib"
    liberty = [
        {
            "corner": "MAX",
            "temperature": 125,
            "path": [
                str(external),
                str(absolute_internal),
                "IP/relative.lib",
                "/IP/legacy.lib",
            ],
            "min_path": [str(external.with_name("sram_min.lib")), "IP/min.lib"],
        }
    ]
    if rc_corner is not None:
        liberty[0]["rc_corner"] = rc_corner
    expected = deepcopy(liberty)
    expected[0]["path"] = [
        str(external),
        str(absolute_internal),
        str(pdk_root / "IP/relative.lib"),
        str(pdk_root / "IP/legacy.lib"),
    ]
    expected[0]["min_path"] = [
        str(external.with_name("sram_min.lib")),
        str(pdk_root / "IP/min.lib"),
    ]
    for value in expected[0]["path"] + expected[0]["min_path"]:
        path = type(tmp_path)(value)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("library(fixture) {}")
    workspace = create_workspace(
        directory=str(tmp_path / "workspace"),
        origin_def="",
        origin_verilog=str(gcd_rtl_file),
        pdk="ics55",
        pdk_root=str(pdk_root),
        parameters={
            **default_ics55_parameters,
            "config_overrides": {"sta": {"liberty": liberty}},
        },
    )
    assert workspace is not None
    config_path = workspace.config[StepEnum.STA.value]
    assert json_read(config_path)["liberty"] == expected

    refresh_workspace_config(workspace)
    assert json_read(config_path)["liberty"] == expected

    step = build_step(workspace, StepEnum.STA.value, input_def=None, input_verilog=None)
    update_step_config(workspace, step)
    assert json_read(config_path)["liberty"] == expected
