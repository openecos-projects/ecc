"""STA library paths survive workspace and per-step override replay."""

from copy import deepcopy

from chipcompiler.data import StepEnum, create_workspace
from chipcompiler.data.workspace import refresh_workspace_config, update_step_config
from chipcompiler.tools.ecc.builder import build_step
from chipcompiler.utility import json_read


def test_sta_refresh_preserves_external_absolute_paths(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters, gcd_rtl_file
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "pdk")
    external = tmp_path / "macro libraries" / "sram.lib"
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
        }
    ]
    expected = deepcopy(liberty)
    expected[0]["path"] = [
        str(external),
        str(absolute_internal),
        str(pdk_root / "IP/relative.lib"),
        str(pdk_root / "IP/legacy.lib"),
    ]
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
