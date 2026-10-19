import pytest

from chipcompiler.data.parameter_schema import lookup_schema, parse_cli_overrides
from chipcompiler.data.workspace_parameters import workspace_param_step
from ecc_experience.dse.plan import validate_parameter_boundary
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.policy import validate_reviewed_values


def test_density_weight_uses_existing_public_workspace_parameter_contract():
    parsed, errors = parse_cli_overrides(["place.density_weight=0.0009"])
    assert errors == []
    assert parsed == {"place.density_weight": 0.0009}
    assert workspace_param_step(lookup_schema("place.density_weight")) == "place"
    validate_parameter_boundary(list(parsed), ["postFloorplan", "place"])
    validate_reviewed_values(parsed, {})
    with pytest.raises(ExperienceError, match="not active"):
        validate_parameter_boundary(list(parsed), ["postFloorplan"])
    with pytest.raises(ExperienceError, match="non-negative"):
        validate_reviewed_values({"place.density_weight": -1}, {})


def test_emir_parameter_uses_the_emir_workspace_step_contract():
    assert workspace_param_step(lookup_schema("emir.technology_file_path")) == "emir"


def test_routing_parameters_require_supported_profile_and_ordered_layers():
    baseline = {"workspaceSpec": {"pdk": {"familyId": "ics55"}, "parameters": {}}}
    validate_reviewed_values({"route.bottom_layer": "MET3", "route.top_layer": "MET5"}, baseline)
    with pytest.raises(ExperienceError, match="exceed"):
        validate_reviewed_values(
            {"route.bottom_layer": "MET5", "route.top_layer": "MET2"}, baseline
        )
    with pytest.raises(ExperienceError, match="ics55"):
        validate_reviewed_values({"route.top_layer": "MET5"}, {})
    with pytest.raises(ExperienceError, match="not active"):
        validate_parameter_boundary(["route.top_layer"], ["postFloorplan", "place", "CTS"])
