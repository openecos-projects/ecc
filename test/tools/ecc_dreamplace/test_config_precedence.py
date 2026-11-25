from pathlib import Path

import pytest

from chipcompiler.data import PDK, OriginDesign, StepEnum, Workspace
from chipcompiler.data.parameter import save_parameter
from chipcompiler.data.workspace import init_workspace_config
from chipcompiler.params import build_step_params, parse_cli_overrides, resolve_parameters
from chipcompiler.tools.ecc_dreamplace import builder as dreamplace_builder
from chipcompiler.utility import json_read


@pytest.mark.parametrize("persist_parameters", [False, True], ids=["memory", "toml"])
@pytest.mark.parametrize("config_key", ["dreamplace", "DreamPlace"])
def test_step_config_keeps_cli_overrides_above_nested_workspace_settings(
    tmp_path, monkeypatch, make_ics55_parameters, persist_parameters, config_key
):
    cli_values, errors = parse_cli_overrides(
        ["placement:place.gpugr_backend=cpu_pr_mt", "placement:place.l_shape_routability_flag=1"]
    )
    assert errors == []
    step_params = build_step_params(resolve_parameters(cli_overrides=cli_values)[0])
    # A workspace-wide patch under either key spelling still reaches the step config.
    config_overrides = {config_key: {"l_shape_update_interval": 12}}
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd"),
        pdk=PDK(
            name="ics55",
            version="v1",
            root=tmp_path / "pdk",
            tech=Path("tech.lef"),
            lefs=[Path("std.lef")],
        ),
        parameters=make_ics55_parameters(
            {
                "dreamplace": {
                    "gpugr_backend": "auto",
                    "l_shape_routability_flag": 0,
                    "l_shape_update_interval": 10,
                    "def_input": "stale.def",
                    "result_dir": "stale-output",
                },
                "config_overrides": config_overrides,
                "step_params": step_params,
            }
        ),
    )
    if persist_parameters:
        workspace.parameters.path = workspace.directory / "home" / "params.toml"
        assert save_parameter(workspace.parameters)
    step = dreamplace_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.PLACEMENT.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    init_workspace_config(workspace)
    config_path = dreamplace_builder.step_config_path(workspace, step)
    expected = dict(
        gpugr_backend="cpu_pr_mt",
        l_shape_routability_flag=1,
        l_shape_update_interval=12,
        def_input=str(step.input.def_),
        verilog_input=str(step.input.verilog),
        result_dir=str(step.data.workdir_for(step.name)),
    )
    monkeypatch.setattr(dreamplace_builder.ecc_builder, "build_step_config", lambda *_: None)

    dreamplace_builder.build_step_config(workspace, step)

    actual = json_read(config_path)
    assert {key: actual[key] for key in expected} == expected
