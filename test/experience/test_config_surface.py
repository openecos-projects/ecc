import json

import pytest

from ecc_experience.dse.config_surface import (
    canonicalize_parameters,
    config_files,
    describe_config_surface,
    parameter_evidence_from_config_receipt,
    validate_config_surface,
    verify_applied_config,
)
from ecc_experience.models import ExperienceError


def test_surface_maps_public_keys_to_iteration_config_files():
    surface = describe_config_surface(
        {
            "floorplan.core_util": 0.4,
            "place.target_density": 0.5,
            "place.target_overflow": 0.08,
            "place.density_weight": 0.0001,
            "place.num_bins_x": 256,
            "timing_opt.hold_margin": 0.05,
        }
    )

    assert surface["schema"] == "ecc-experience-dse-config-surface/1"
    assert surface["unmapped"] == []
    assert surface["files"] == {
        "dreamplace_ecc.json": [
            "place.density_weight",
            "place.num_bins_x",
            "place.target_density",
            "place.target_overflow",
        ],
        "floorplan_ecc.json": ["floorplan.core_util"],
        "sizer_ecc.json": ["timing_opt.hold_margin"],
    }
    entries = {item["parameter"]: item for item in surface["entries"]}
    assert entries["floorplan.core_util"]["json_paths"] == [
        ["die_builder", "die_util", "utilization"]
    ]
    assert entries["place.target_density"]["json_paths"] == [["target_density"]]
    assert entries["place.target_overflow"]["json_paths"] == [["stop_overflow"]]
    assert entries["place.density_weight"]["json_paths"] == [["density_weight"]]
    assert entries["timing_opt.hold_margin"]["json_paths"] == [["hold_stage", "hold_margin"]]
    assert all(item["application"] == "workspace_param_apply" for item in surface["entries"])


def test_surface_describes_multi_path_floorplan_margin():
    surface = describe_config_surface({"floorplan.core_margin": [2, 3]})

    entry = surface["entries"][0]
    assert entry["config_file"] == "floorplan_ecc.json"
    assert entry["json_paths"] == [
        ["die_builder", "margin", "left_micron"],
        ["die_builder", "margin", "right_micron"],
        ["die_builder", "margin", "top_micron"],
        ["die_builder", "margin", "bottom_micron"],
    ]


def test_surface_rejects_a_key_with_no_tool_config_effect():
    assert describe_config_surface({"place.global_right_padding": 4})["unmapped"] == [
        "place.global_right_padding"
    ]
    with pytest.raises(ExperienceError, match="no iteration config-file effect"):
        validate_config_surface({"place.global_right_padding": 4})


def test_config_files_returns_the_primary_files_deterministically():
    assert config_files(["place.density_weight", "floorplan.core_util"]) == [
        "dreamplace_ecc.json",
        "floorplan_ecc.json",
    ]


def test_config_receipt_verifies_the_values_in_each_iteration_config(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "dreamplace_ecc.json").write_text(
        json.dumps({"target_density": 0.55, "density_weight": 0.00012})
    )
    (config / "floorplan_ecc.json").write_text(
        json.dumps({"die_builder": {"die_util": {"utilization": 0.38}}})
    )
    (config / "sizer_ecc.json").write_text(json.dumps({"hold_stage": {"hold_margin": 0.06}}))

    receipt = verify_applied_config(
        tmp_path,
        {
            "place.target_density": 0.55,
            "place.density_weight": 0.00012,
            "floorplan.core_util": 0.38,
            "timing_opt.hold_margin": 0.06,
        },
    )

    assert receipt["schema"] == "ecc-experience-dse-config-receipt/1"
    assert receipt["status"] == "applied"
    assert receipt["reason"] is None
    assert receipt["files"] == [
        "dreamplace_ecc.json",
        "floorplan_ecc.json",
        "sizer_ecc.json",
    ]
    assert len(receipt["checks"]) == 4
    assert receipt["mismatches"] == []


def test_config_receipt_reports_a_value_that_did_not_land(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "dreamplace_ecc.json").write_text(json.dumps({"target_density": 0.4}))

    receipt = verify_applied_config(tmp_path, {"place.target_density": 0.55})

    assert receipt["status"] == "mismatch"
    assert receipt["mismatches"] == [
        {
            "parameter": "place.target_density",
            "config_file": "dreamplace_ecc.json",
            "json_path": ["target_density"],
            "expected": 0.55,
            "observed": 0.4,
            "match": False,
        }
    ]


def test_config_receipt_does_not_claim_an_unreadable_file_was_applied(tmp_path):
    receipt = verify_applied_config(tmp_path, {"place.target_density": 0.55})

    assert receipt["status"] == "unavailable"
    assert "dreamplace_ecc.json" in receipt["reason"]


def test_config_receipt_becomes_materialization_evidence_not_runtime_effectiveness(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "dreamplace_ecc.json").write_text(
        json.dumps({"target_density": 0.55, "stop_overflow": 0.08})
    )
    parameters = {"place.target_density": 0.55, "place.target_overflow": 0.08}
    receipt = verify_applied_config(tmp_path, parameters)

    evidence = parameter_evidence_from_config_receipt(
        receipt, parameters, candidate_id="candidate-0001", stage="place"
    )

    assert evidence is not None
    assert evidence["level"] == "materialized"
    assert evidence["receipt_status"] == "valid"
    assert len(evidence["receipt_sha256"]) == 64
    assert {item["knob_id"] for item in evidence["applied_parameters"]} == set(parameters)
    assert all(item["status"] == "unknown" for item in evidence["applied_parameters"])
    assert "not runtime consumption" in evidence["limitations"][0]


def test_unapplied_config_receipt_does_not_create_evidence(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "dreamplace_ecc.json").write_text(json.dumps({"target_density": 0.4}))
    receipt = verify_applied_config(tmp_path, {"place.target_density": 0.55})

    assert parameter_evidence_from_config_receipt(receipt, {"place.target_density": 0.55}) is None


def test_parameter_aliases_collapse_to_the_supported_key():
    canonical = canonicalize_parameters(
        {
            "place.target_overflow": 0.08,
            "place.stop_overflow": 0.08,
            "place.timing_opt_max_windows": 3,
            "place.inflation_s5b1_max_windows": 3,
            "place.density_weight": 0.0001,
        }
    )

    assert canonical == {
        "place.target_overflow": 0.08,
        "place.timing_opt_max_windows": 3,
        "place.density_weight": 0.0001,
    }


def test_alias_readback_does_not_look_like_an_unauthorized_change():
    from ecc_experience.optimization.policy import configuration_differences

    baseline = {
        "place.target_overflow": 0.1,
        "place.stop_overflow": 0.1,
        "place.routability_opt": 1,
        "place.routability_opt_flag": 1,
    }
    observed = {
        "place.target_overflow": 0.08,
        "place.stop_overflow": 0.08,
        "place.routability_opt": 1,
        "place.routability_opt_flag": 1,
    }

    assert configuration_differences(baseline, observed) == {"place.target_overflow"}
