"""Step-scoped (DreamPlace) parameters: one value per declared flow step."""

from pathlib import Path

import pytest

from chipcompiler.data import PDK, OriginDesign, Workspace
from chipcompiler.data.parameter import get_parameters
from chipcompiler.data.step_parameters import ParameterStepError, step_parameter_view
from chipcompiler.data.workspace import init_workspace_config
from chipcompiler.params import (
    invalid_carried_parameters,
    lookup_schema,
    parse_cli_overrides,
    parse_toml_params,
    unset_workspace_param,
    update_workspace_param_value,
    workspace_param_diff,
    workspace_param_value,
)
from test.flow_fixture import current_flow_document


def _workspace(tmp_path: Path) -> Workspace:
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd"),
        pdk=PDK(tech=Path("tech.lef"), lefs=[Path("std.lef")]),
        parameters=get_parameters("ics55"),
    )
    init_workspace_config(workspace)
    workspace.flow.data = current_flow_document(
        {"name": name, "tool": "dreamplace", "state": "Unstart"}
        for name in ("placement", "diff_opt")
    )
    return workspace


def _schema(param: str):
    schema = lookup_schema(param)
    assert schema is not None
    return schema


def test_each_declared_step_holds_its_own_value(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    schema = _schema("place.timing_sizing_action")
    baseline = workspace_param_value(workspace, schema)
    other = next(choice for choice in schema.choices or () if choice != baseline)

    update_workspace_param_value(workspace, schema, other, step="diff_opt")

    assert {
        step: workspace_param_value(workspace, schema, step=step)
        for step in ("placement", "diff_opt")
    } == {"placement": baseline, "diff_opt": other}
    assert workspace_param_diff(workspace) == [
        {
            "key": "place.timing_sizing_action",
            "baseline": baseline,
            "step": "diff_opt",
            "stored": False,
            "value": other,
        }
    ]


def test_unset_drops_a_step_value_the_step_did_not_have(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    schema = _schema("place.target_density")

    update_workspace_param_value(workspace, schema, 0.7, step="placement")
    unset_workspace_param(workspace, schema, "placement")

    assert "step_params" not in workspace.parameters.data
    assert workspace_param_diff(workspace) == []


@pytest.mark.parametrize(
    ("step", "code"),
    [(None, "parameter_step_required"), ("cts", "parameter_not_applicable")],
)
def test_a_dreamplace_parameter_needs_one_of_its_steps(tmp_path, step, code) -> None:
    workspace = _workspace(tmp_path)

    with pytest.raises(ParameterStepError) as error:
        update_workspace_param_value(workspace, _schema("place.target_density"), 0.7, step=step)

    assert error.value.code == code


def test_project_inputs_name_the_step_in_the_key() -> None:
    toml = parse_toml_params(
        {"step": {"placement": {"place": {"target_density": 0.7}}}, "cts": {"skew_bound": "0.1"}}
    )
    cli = parse_cli_overrides(["placement:place.target_density=0.6", "place.target_density=0.6"])

    assert (toml, cli) == (
        ({"placement:place.target_density": 0.7, "cts.skew_bound": "0.1"}, []),
        (
            {"placement:place.target_density": 0.6},
            ["place.target_density is set per step; name one of: placement"],
        ),
    )


def test_a_step_view_replays_the_step_values_as_its_config_patch() -> None:
    parameters = {
        "config_overrides": {"routing": {"RT": {"-thread_number": 4}}},
        "step_params": {"placement": {"place.target_density": 0.7}},
    }

    assert step_parameter_view(parameters, "placement")["config_overrides"] == {
        "routing": {"RT": {"-thread_number": 4}},
        "dreamplace": {"target_density": 0.7},
    }
    assert step_parameter_view(parameters, "diff_opt") == parameters


def test_carried_step_values_must_name_a_declared_step_of_the_new_flow() -> None:
    carried = {
        "step_params": {
            "placement": {"place.target_density": 0.7},
            "legalization": {"place.target_density": 0.7},
        },
        "workspace_param_overrides": [
            {"key": "place.timing_sizing_action", "step": "diff_opt", "baseline": "up"},
            {"key": "cts.skew_bound", "step": "cts", "baseline": "0.1"},
        ],
    }

    assert invalid_carried_parameters(carried, "ics55", ["synthesis", "placement"]) == [
        "place.target_density does not apply to step legalization",
        "diff_opt:place.timing_sizing_action: step diff_opt is not in the new flow",
        "cts.skew_bound is workspace-wide but was carried at step cts",
    ]
    assert invalid_carried_parameters({"step_params": carried["step_params"]}, "ics55") == [
        "place.target_density does not apply to step legalization"
    ]
