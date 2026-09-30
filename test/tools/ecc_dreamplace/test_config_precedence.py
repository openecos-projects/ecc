from copy import deepcopy

import pytest

from chipcompiler.data import PDK, OriginDesign, StepEnum, Workspace
from chipcompiler.data.parameter import save_parameter
from chipcompiler.data.parameter_schema import (
    build_config_overrides,
    parse_cli_overrides,
    resolve_parameters,
)
from chipcompiler.data.workspace import init_workspace_config
from chipcompiler.tools.ecc_dreamplace import builder as dreamplace_builder
from chipcompiler.utility import json_read


@pytest.mark.parametrize("persist_parameters", [False, True], ids=["memory", "toml"])
@pytest.mark.parametrize("config_key", ["dreamplace", "DreamPlace"])
def test_step_config_keeps_cli_overrides_above_nested_workspace_settings(
    tmp_path, monkeypatch, make_ics55_parameters, persist_parameters, config_key
):
    cli_values, errors = parse_cli_overrides(
        ["place.gpugr_backend=cpu_pr_mt", "place.l_shape_routability_flag=1"]
    )
    assert errors == []
    resolved, errors = resolve_parameters(cli_overrides=cli_values)
    assert errors == []
    config_overrides = build_config_overrides(resolved)
    config_overrides[config_key] = config_overrides.pop("dreamplace")
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd"),
        pdk=PDK(tech="tech.lef", lefs=["std.lef"]),
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
    config_path = workspace.config["dreamplace"]
    expected = deepcopy(json_read(config_path))
    expected.update(
        gpugr_backend="cpu_pr_mt",
        l_shape_routability_flag=1,
        l_shape_update_interval=10,
        def_input=str(step.input.def_),
        verilog_input=str(step.input.verilog),
        result_dir=str(step.data.workdir_for(step.name)),
    )
    monkeypatch.setattr(dreamplace_builder.ecc_builder, "build_step_config", lambda *_: None)

    dreamplace_builder.build_step_config(workspace, step)

    assert json_read(config_path) == expected
