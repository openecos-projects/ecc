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
    workspace = _workspace("synthesis", "placement", "routing")

    assert workspace_param_step(_schema("flow.run_analysis"), workspace) == "synthesis"


def test_a_multi_step_parameter_picks_the_earliest_matching_flow_step() -> None:
    schema = _schema("place.timing_sizing_action")

    assert schema.applies == "placement,diff_opt"
    assert workspace_param_step(schema, _workspace("diff_opt", "placement")) == "diff_opt"
    assert workspace_param_step(schema, _workspace("placement", "diff_opt")) == "placement"


def test_a_flow_wide_parameter_is_settable_without_a_workspace() -> None:
    assert workspace_param_step(_schema("flow.run_analysis")) == "all"


@pytest.mark.parametrize("param", ["pdk.tech", "pdk.libs"])
def test_pdk_content_parameters_need_a_full_workspace_refresh(param: str) -> None:
    schema = _schema(param)

    with pytest.raises(ValueError, match="requires a full workspace refresh"):
        workspace_param_step(schema)
    with pytest.raises(ValueError, match="requires a full workspace refresh"):
        workspace_param_value(SimpleNamespace(), schema)


def test_a_routing_layer_invalidates_from_placement_whose_gpugr_layers_it_sets() -> None:
    workspace = _workspace("synthesis", "placement", "cts", "routing")

    assert workspace_param_step(_schema("route.top_layer"), workspace) == "placement"


def test_a_workspace_value_invalidates_from_the_first_step_reading_one_of_its_configs() -> None:
    steps = [
        {"name": name, "tool": tool}
        for name, tool in (
            ("synthesis", "yosys"),
            ("pre_floorplan", "ecc"),
            ("macro_placement", "dreamplace"),
            ("placement", "dreamplace"),
            ("cts", "ecc"),
            ("routing", "ecc"),
        )
    ]
    workspace = SimpleNamespace(flow=SimpleNamespace(steps=lambda: steps))

    # bottom_layer is also written into the floorplan ``db`` config;
    # top_layer into the DreamPlace baseline macro_placement reads.
    assert {
        param: workspace_param_step(_schema(param), workspace)
        for param in ("route.bottom_layer", "route.top_layer", "cts.max_fanout")
    } == {
        "route.bottom_layer": "pre_floorplan",
        "route.top_layer": "macro_placement",
        "cts.max_fanout": "cts",
    }
