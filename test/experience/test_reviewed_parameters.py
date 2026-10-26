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


def test_reviewed_config_parameters_use_public_workspace_targets():
    expected = {
        "place.gamma": ("place", ("dreamplace", "gamma")),
        "place.node_area_adjust_overflow": (
            "place",
            ("dreamplace", "node_area_adjust_overflow"),
        ),
        "place.timing_opt_max_windows": ("place", ("dreamplace", "timing_opt_max_windows")),
        "timing_opt.hold_margin": ("Timing optimization", ("sizer", "hold_stage", "hold_margin")),
        "timing_opt.placement_wire_resistance_ohm_per_um": (
            "Timing optimization",
            ("sizer", "hold_stage", "placement_wire_rc", "resistance_ohm_per_um"),
        ),
    }
    for key, (step, target) in expected.items():
        schema = lookup_schema(key)
        assert workspace_param_step(schema) == step
        assert (schema.config_target.config_key, *schema.config_target.json_path) == target


def test_placement_and_sizer_ranges_are_reviewed_and_stage_bounded():
    parameters, errors = parse_cli_overrides(
        [
            "place.gamma=8",
            "place.gp_noise_ratio=0.02",
            "place.timing_aggregation_tau_ps=4",
            "timing_opt.hold_margin=0.08",
        ]
    )
    assert errors == []
    validate_reviewed_values(parameters, {})
    names = ["Synthesis", "postFloorplan", "place", "CTS", "legalization", "Timing optimization"]
    validate_parameter_boundary(list(parameters), names)
    with pytest.raises(ExperienceError, match="not active"):
        validate_parameter_boundary(["timing_opt.hold_margin"], names[:-1])
    with pytest.raises(ExperienceError, match="outside"):
        validate_reviewed_values({"place.gp_noise_ratio": 1.0}, {})
    with pytest.raises(ExperienceError, match="outside"):
        validate_reviewed_values({"timing_opt.hold_margin": -0.1}, {})


def test_placement_bin_and_routability_knobs_are_reviewed():
    parameters, errors = parse_cli_overrides(
        [
            "place.num_bins_x=512",
            "place.num_bins_y=512",
            "place.max_route_opt_adjust_rate=2.5",
            "place.max_pin_opt_adjust_rate=2.0",
            "place.pin_stretch_ratio=1.5",
            "place.timing_rc_mode=gr",
            "place.with_sta=1",
            "place.diff_timing_driven_placement=1",
        ]
    )
    assert errors == []
    assert parameters["place.num_bins_x"] == 512
    assert parameters["place.timing_rc_mode"] == "gr"
    validate_reviewed_values(parameters, {})
    with pytest.raises(ExperienceError, match="outside"):
        validate_reviewed_values({"place.num_bins_x": 4096}, {})
    with pytest.raises(ExperienceError, match="outside"):
        validate_reviewed_values({"place.pin_stretch_ratio": 0.5}, {})


def test_noop_placement_padding_is_not_a_supported_dse_axis():
    from ecc_experience.optimization.policy import SUPPORTED_PARAMETERS

    assert "place.global_right_padding" not in SUPPORTED_PARAMETERS
