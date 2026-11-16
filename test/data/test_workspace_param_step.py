"""workspace_param_step: which flow step a post-creation parameter change invalidates."""

from types import SimpleNamespace

import pytest

from chipcompiler.params import lookup_schema, workspace_param_step, workspace_param_value


def _workspace(*names: str) -> SimpleNamespace:
    steps = [{"name": name} for name in names]
    return SimpleNamespace(flow=SimpleNamespace(steps=lambda: steps))


def _schema(param: str):
    schema = lookup_schema(param)
    assert schema is not None
    return schema


def test_a_flow_wide_parameter_invalidates_from_the_first_flow_step() -> None:
    workspace = _workspace("Synthesis", "place", "route")

    assert workspace_param_step(_schema("sdc.clk_group_txt"), workspace) == "Synthesis"


def test_a_multi_step_parameter_picks_the_earliest_matching_flow_step() -> None:
    schema = _schema("place.timing_sizing_action")

    assert schema.applies == "placement,diff_opt"
    assert workspace_param_step(schema, _workspace("diff_opt", "place")) == "diff_opt"
    assert workspace_param_step(schema, _workspace("place", "diff_opt")) == "place"


def test_a_flow_wide_parameter_is_settable_without_a_workspace() -> None:
    assert workspace_param_step(_schema("sdc.clk_group_txt")) == "all"


@pytest.mark.parametrize("param", ["pdk.tech", "pdk.libs"])
def test_pdk_content_parameters_need_a_full_workspace_refresh(param: str) -> None:
    schema = _schema(param)

    with pytest.raises(ValueError, match="requires a full workspace refresh"):
        workspace_param_step(schema)
    with pytest.raises(ValueError, match="requires a full workspace refresh"):
        workspace_param_value(SimpleNamespace(), schema)
