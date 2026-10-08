"""Public parameter handoff and geometry isolation for GR timing."""

import json

import pytest

from chipcompiler.cli.project.params import (
    build_config_overrides,
    parse_toml_params,
    resolve_parameters,
)
from chipcompiler.data import EccData, EccStep, OriginDesign, StepEnum, Workspace
from chipcompiler.data.workspace.config_overrides import apply_config_overrides
from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule, DreamplaceRunMode

from .test_module import FakeParams


def test_gr_public_handoff_and_geometry_isolation(tmp_path, dreamplace_default_config, monkeypatch):
    values = {
        "flow_kind": "sizing",
        "place_io_engine": "ecc",
        "timing_rc_mode": "gr",
        "timing_opt_enabled": 0,
        "routability_opt_flag": 0,
        "l_shape_routability_flag": 0,
        "adjust_gpugr_area_flag": 0,
        "cell_model_schema": "main_id_arc_offset_piecewise_linear",
        "piecewise_gradient_mode": "native_piecewise",
        "timing_surrogate_mode": "mixed",
    }
    parsed, errors = parse_toml_params({"place": values})
    assert errors == []
    resolved, errors = resolve_parameters(toml_overrides=parsed)
    assert errors == []
    path = tmp_path / "dreamplace.json"
    path.write_text(json.dumps(dreamplace_default_config))
    apply_config_overrides(
        {"dreamplace": path}, {"config_overrides": build_config_overrides(resolved)}
    )
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="clocked"),
        config={"dreamplace": path},
    )
    workspace.pdk.spef = tmp_path / "stale.spef"
    workspace.config[StepEnum.RCX.value] = tmp_path / "rcx.json"
    monkeypatch.setattr(workspace.flow, "has_step", lambda _step: True)
    step = EccStep(
        name=StepEnum.PLACEMENT.value,
        data=EccData(steps={StepEnum.PLACEMENT.value: tmp_path / "pl"}),
    )
    module = DreamplaceModule(workspace, step, None, None, None, None, None)
    actual = module._build_params(FakeParams, mode=DreamplaceRunMode.PLACEMENT)
    assert {key: getattr(actual, key) for key in values} == {
        **values,
        "timing_surrogate_mode": "surrogate_only",
    }
    assert (actual.design_inputs["spef"], actual.design_inputs["rcx_config"]) == ("", "")
    geometry = module._build_params(FakeParams, mode=DreamplaceRunMode.LEGALIZATION)
    assert (geometry.timing_rc_mode, geometry.with_sta) == ("placement", 0)


@pytest.mark.parametrize(
    "override",
    [
        {"gpu": 1},
        {"gpugr_backend": "cuda"},
        {"flow_kind": "joint"},
        {"place_io_engine": "openroad"},
        {"placement_sizing_mode": "joint"},
    ],
)
def test_gr_rejects_unqualified_flows(override, dreamplace_default_config):
    from dreamplace.flows.flow_config import resolve_flow_config

    config = {
        **dreamplace_default_config,
        "flow_kind": "sizing",
        "timing_rc_mode": "gr",
        "place_io_engine": "ecc",
        "timing_opt_enabled": 0,
        **override,
    }
    with pytest.raises(ValueError, match="GR timing"):
        resolve_flow_config(config, explicit_keys=tuple(config))


@pytest.mark.parametrize(
    ("requested", "expected"),
    [("auto", "cpu_pr_mt"), ("cpu_pr", "cpu_pr"), ("cpu_pr_mt", "cpu_pr_mt")],
)
def test_gr_routing_stays_on_cpu(requested, expected, dreamplace_default_config, monkeypatch):
    import torch
    from dreamplace.flows.flow_config import resolve_flow_config

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    config = {
        **dreamplace_default_config,
        "flow_kind": "sizing",
        "timing_rc_mode": "gr",
        "place_io_engine": "ecc",
        "timing_opt_enabled": 0,
        "routability_opt_flag": 0,
        "l_shape_routability_flag": 0,
        "adjust_gpugr_area_flag": 0,
        "gpugr_backend": requested,
    }
    resolved = resolve_flow_config(config, explicit_keys=tuple(config))
    assert {key: resolved[key] for key in ("gpu", "gpugr_backend")} == {
        "gpu": 0,
        "gpugr_backend": expected,
    }
