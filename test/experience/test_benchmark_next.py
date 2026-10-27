import json

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from ecc_experience.knowledge.campaign import CAMPAIGN_MANIFEST_SCHEMA
from ecc_experience.knowledge.iteration import NEXT_SCHEMA, plan_next_benchmark
from ecc_experience.models import ExperienceError


def _run(
    design,
    strategy,
    seed=1,
    *,
    family="family-a",
    status="complete",
    fresh="passed",
    quality="high",
    selected=1.0,
    model="not_requested",
    resource=True,
    feature=True,
):
    return {
        "design": design,
        "family": family,
        "strategy": strategy,
        "seed": seed,
        "status": status,
        "full_validation": "passed",
        "fresh_validation": fresh,
        "selected_parameters": {"axis": selected},
        "quality": {
            "level": quality,
            "checks": {
                "resource_available": resource,
                "feature_usable": feature,
            },
        },
        "model": {"status": model},
        "budget": {"limits": {"max_seconds": 60, "max_trials": 4}},
    }


def _manifest():
    runs = [
        _run("design-a", "grid"),
        _run("design-a", "adaptive", fresh="timeout", quality="medium"),
        _run("design-a", "adaptive_warm", selected=2.0),
        _run("design-a", "model_assisted", model="unknown"),
        _run("design-b", "grid"),
        _run("design-b", "adaptive"),
        _run("design-b", "adaptive_warm"),
        _run("design-b", "model_assisted", model="available"),
        _run("design-c", "grid"),
    ]
    return {
        "schema": CAMPAIGN_MANIFEST_SCHEMA,
        "campaign_id": "campaign-next",
        "budget": {"equal_budget": True},
        "runs": runs,
        "search": {
            "space_coverage": {
                "axes": {
                    "core_util": {
                        "status": "upper_boundary",
                        "lower_bound": 0.32,
                        "upper_bound": 0.4,
                        "selected_values": [0.4],
                    },
                    "density": {
                        "status": "interior",
                        "lower_bound": 0.2,
                        "upper_bound": 0.4,
                        "selected_values": [0.3],
                    },
                }
            }
        },
        "model_evidence": {
            "calibration": {
                "status": "insufficient_evidence",
                "pair_count": 1,
                "design_count": 1,
                "family_count": 1,
            }
        },
    }


def test_next_round_prioritizes_missing_matrix_and_confirmation_gap(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest()))

    result = plan_next_benchmark(manifest, tmp_path / "next.json")

    assert result["schema"] == NEXT_SCHEMA
    assert result["status"] == "action_required"
    assert result["budget"]["exploration"]["run_count_floor"] == 4
    assert result["budget"]["confirmation"]["minimum_new_designs"] == 3
    assert result["budget"]["confirmation"]["minimum_additional_seed_runs"] == 12
    assert result["budget"]["confirmation"]["minimum_runs"] == 36
    assert result["budget"]["per_run_limits"] == [{"max_seconds": 60, "max_trials": 4}]
    assert result["policy"]["safe_to_apply"] is False
    priorities = {row["design"]: row for row in result["priorities"]}
    assert priorities["design-a"]["priority"] == "high"
    assert priorities["design-a"]["next_action"] == "rerun_invalid_runs"
    assert priorities["design-b"]["priority"] == "medium"
    assert priorities["design-b"]["strategy_separation"] == "converged"
    assert priorities["design-c"]["priority"] == "high"
    assert priorities["design-c"]["strategies_missing"] == [
        "adaptive",
        "adaptive_warm",
        "model_assisted",
    ]
    codes = {action["code"] for action in result["actions"]}
    assert {
        "independent_design_coverage",
        "family_coverage",
        "seed_coverage",
        "search_space_adjustment",
        "model_calibration",
    } <= codes


def test_next_round_is_ready_only_when_gates_and_evidence_are_complete(tmp_path):
    runs = []
    for design_index in range(6):
        for seed in (1, 2):
            for strategy_index, strategy in enumerate(
                ("grid", "adaptive", "adaptive_warm", "model_assisted")
            ):
                runs.append(
                    _run(
                        f"design-{design_index}",
                        strategy,
                        seed,
                        family=f"family-{design_index % 3}",
                        selected=float(strategy_index),
                        model="available" if strategy == "model_assisted" else "not_requested",
                    )
                )
    manifest = {
        "schema": CAMPAIGN_MANIFEST_SCHEMA,
        "campaign_id": "campaign-ready",
        "budget": {"equal_budget": True},
        "runs": runs,
        "search": {
            "space_coverage": {
                "axes": {
                    "core_util": {
                        "status": "interior",
                        "lower_bound": 0.32,
                        "upper_bound": 0.48,
                        "selected_values": [0.4],
                    }
                }
            }
        },
        "model_evidence": {
            "calibration": {
                "status": "available",
                "pair_count": 6,
                "design_count": 6,
                "family_count": 3,
            }
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    result = plan_next_benchmark(path, tmp_path / "next.json")

    assert result["status"] == "ready_for_confirmation"
    assert result["actions"] == []
    assert result["budget"]["exploration"]["run_count_floor"] == 0
    assert result["budget"]["confirmation"]["minimum_runs"] == 0
    assert {row["priority"] for row in result["priorities"]} == {"low"}


def test_next_round_rejects_reused_output_and_invalid_manifest(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest()))
    output = tmp_path / "next.json"
    output.write_text("{}")
    with pytest.raises(ExperienceError, match="new file"):
        plan_next_benchmark(manifest, output)

    manifest.write_text(json.dumps({"schema": "unknown", "runs": []}))
    with pytest.raises(ExperienceError, match="campaign manifest"):
        plan_next_benchmark(manifest, tmp_path / "other.json")


def test_next_round_cli_exposes_planning_only_output(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest()))
    output = tmp_path / "next.json"

    result = CliRunner().invoke(
        app,
        [
            "experience",
            "knowledge",
            "next",
            "--manifest",
            str(manifest),
            "--output",
            str(output),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)[0]
    assert payload["experience"] == "benchmark_next"
    assert payload["policy"]["planning_only"] is True


def test_next_round_does_not_treat_seed_variation_as_strategy_separation(tmp_path):
    runs = []
    for seed, selected in ((1, 1.0), (2, 2.0)):
        for strategy in ("grid", "adaptive", "adaptive_warm", "model_assisted"):
            runs.append(
                _run(
                    "design-a",
                    strategy,
                    seed,
                    family="family-a",
                    selected=selected,
                    model="available" if strategy == "model_assisted" else "not_requested",
                )
            )
    manifest = {
        "schema": CAMPAIGN_MANIFEST_SCHEMA,
        "campaign_id": "campaign-seed-variation",
        "budget": {"equal_budget": True},
        "runs": runs,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    result = plan_next_benchmark(path, tmp_path / "next.json")

    priority = result["priorities"][0]
    assert priority["strategy_separation"] == "converged"
    assert {"code": "strategies_converged"} in priority["reasons"]


def test_next_round_repeats_matched_seeds_when_seed_conclusions_disagree(tmp_path):
    runs = []
    for seed, separated in ((1, True), (2, False)):
        for index, strategy in enumerate(
            ("grid", "adaptive", "adaptive_warm", "model_assisted")
        ):
            runs.append(
                _run(
                    "design-a",
                    strategy,
                    seed,
                    selected=float(index) if separated else 1.0,
                    model="available" if strategy == "model_assisted" else "not_requested",
                )
            )
    manifest = {
        "schema": CAMPAIGN_MANIFEST_SCHEMA,
        "campaign_id": "campaign-unstable-separation",
        "budget": {"equal_budget": True},
        "runs": runs,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    result = plan_next_benchmark(path, tmp_path / "next.json")

    priority = result["priorities"][0]
    assert priority["strategy_separation"] == "unstable"
    assert priority["priority"] == "medium"
    assert {"code": "strategy_separation_unstable"} in priority["reasons"]
    assert priority["next_action"] == "repeat_matched_seeds"


def test_next_round_flags_cartesian_space_larger_than_trial_budget(tmp_path):
    manifest = _manifest()
    manifest["search"]["space_coverage"]["cartesian_coverage"] = {
        "status": "budget_limited",
        "declared_combination_counts": [27],
        "trial_budget_limits": [16],
        "budget_limited_runs": ["design-a:grid:1"],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    result = plan_next_benchmark(path, tmp_path / "next.json")

    assert {
        "code": "search_space_budget",
        "priority": "high",
        "status": "budget_limited",
        "declared_combination_counts": [27],
        "trial_budget_limits": [16],
        "budget_limited_runs": ["design-a:grid:1"],
        "reason": (
            "The declared Cartesian space is larger than max_trials; reduce the combination "
            "count or freeze a larger equal per-run budget instead of presenting a partial "
            "grid as full coverage"
        ),
    } in result["actions"]
