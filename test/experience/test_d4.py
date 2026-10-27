import json

from typer.testing import CliRunner

from chipcompiler.cli.app import app
from ecc_experience.api import d4_evaluate
from ecc_experience.benchmark.d4 import (
    _resource_evidence,
    _summarize_resources,
    _warm_start_evidence,
)

STRATEGIES = ("grid", "adaptive", "adaptive_warm", "model_assisted")


def _plan(strategy, design, family):
    warm = (
        [{"case_id": "candidate", "confidence": "experimental"}]
        if strategy == "adaptive_warm"
        else []
    )
    return {
        "schema": "ecc-experience-stage-dse-plan/2",
        "plan_fingerprint": f"plan-{strategy}-{design}-{family}",
        "strategy": "grid" if strategy == "grid" else "adaptive",
        "input_content_fingerprint": f"input-{design}",
        "process": {"status": "available", "fingerprint": "process"},
        "runtime": {"ecc": "test"},
        "objectives": [{"id": "qor", "direction": "minimize"}],
        "space": {"floorplan.core_util": [0.3, 0.4]},
        "limits": {"max_trials": 4, "max_seconds": 60, "trial_timeout_seconds": 30},
        "screening_trials": 2,
        "rungs": [{"through_step": "floorplan", "promote_count": 1}],
        "warm_start": {
            "seeds": warm,
            "experimental_cross_design": bool(warm),
            "family_isolation": "explicit_groups" if warm else "not_checked",
        },
    }


def _result(plan, strategy, score):
    return {
        "schema": "ecc-experience-stage-dse-result/2",
        "plan_fingerprint": plan["plan_fingerprint"],
        "status": "complete",
        "elapsed_seconds": 20.0,
        "model": {
            "status": "available" if strategy == "model_assisted" else "not_requested",
            "requested": "release.json" if strategy == "model_assisted" else None,
            "release_id": "release-model" if strategy == "model_assisted" else None,
            "model_id": "model-a" if strategy == "model_assisted" else None,
            "policy": "measured_objective_tie_break_only",
            "used_for_selection": False,
        },
        "trials": [
            {
                "candidate_id": f"candidate-{index}",
                "parameters": {"floorplan.core_util": 0.3 + index / 10},
                "mode": "screen",
                "status": "stage_passed",
                "exit_code": 0,
                "commands": [],
                "elapsed_seconds": 5.0,
            }
            for index in range(2)
        ],
        "full_validation": {"status": "passed", "qor_score": score},
        "fresh_validation": {"status": "passed", "qor_score": score},
        "selection": {"candidate": "candidate-0", "rule": "single_objective"},
    }


def _write_spec(tmp_path, *, designs=6, seeds=2):
    runs = []
    families = ("arithmetic", "memory", "control")
    for design_index in range(designs):
        design = f"design-{design_index}"
        family = families[design_index % len(families)]
        for seed in range(seeds):
            for order, strategy in enumerate(STRATEGIES):
                plan = _plan(strategy, design, family)
                plan_path = tmp_path / f"{design}-{seed}-{strategy}-plan.json"
                result_path = tmp_path / f"{design}-{seed}-{strategy}-result.json"
                plan_path.write_text(json.dumps(plan))
                scores = {
                    "grid": 93.0,
                    "adaptive": 92.0,
                    "adaptive_warm": 91.0,
                    "model_assisted": 90.0,
                }
                result_path.write_text(json.dumps(_result(plan, strategy, scores[strategy])))
                runs.append(
                    {
                        "design": design,
                        "family": family,
                        "strategy": strategy,
                        "seed": seed,
                        "order": (len(STRATEGIES) - 1 - order if seed % 2 else order),
                        "host_class": "test-host",
                        "plan": plan_path.name,
                        "result": result_path.name,
                    }
                )
    spec = tmp_path / "d4.json"
    spec.write_text(json.dumps({"schema": "ecc-experience-d4-spec/1", "runs": runs}))
    return spec


def test_d4_requires_multi_design_family_and_seed_evidence(tmp_path):
    report = d4_evaluate(_write_spec(tmp_path), tmp_path / "report.json")

    assert report["status"] == "pass"
    assert report["generalization_status"] == "validated_for_declared_scope"
    assert report["summary"]["design_count"] == 6
    assert report["summary"]["family_count"] == 3
    assert report["summary"]["seed_count"] == 2
    assert report["safe_to_apply"] is False
    assert report["promotion_allowed"] is True


def test_d4_insufficient_sample_stays_unknown(tmp_path):
    report = d4_evaluate(_write_spec(tmp_path, designs=5), tmp_path / "report.json")

    assert report["status"] == "unknown"
    assert report["exit_code"] == 7
    assert report["generalization_status"] == "unproven"
    assert report["promotion_allowed"] is False
    assert "insufficient_independent_designs" in report["reasons"]


def test_d4_equal_budget_ignores_algorithm_patience_and_trial_timeout(tmp_path):
    spec = _write_spec(tmp_path)
    plan_path = tmp_path / "design-0-0-grid-plan.json"
    plan = json.loads(plan_path.read_text())
    plan["limits"]["patience"] = 1
    plan["limits"]["trial_timeout_seconds"] = 90
    plan_path.write_text(json.dumps(plan))

    report = d4_evaluate(spec, tmp_path / "report.json")

    assert report["status"] == "pass"
    assert report["summary"]["equal_budget"] is True


def test_d4_rejects_same_input_warm_start_as_a_distinct_strategy(tmp_path):
    spec = _write_spec(tmp_path)
    plan_path = tmp_path / "design-0-0-adaptive_warm-plan.json"
    plan = json.loads(plan_path.read_text())
    plan["warm_start"]["seeds"][0]["confidence"] = "observed_only"
    plan["warm_start"]["experimental_cross_design"] = False
    plan["warm_start"]["family_isolation"] = "not_checked"
    plan_path.write_text(json.dumps(plan))

    report = d4_evaluate(spec, tmp_path / "report.json")

    assert report["status"] == "unknown"
    assert "warm_start_not_cross_design:design-0" in report["reasons"]
    assert "warm_start_family_isolation_missing:design-0" in report["reasons"]


def test_d4_reports_the_iteration_config_files_each_strategy_explored(tmp_path):
    report = d4_evaluate(_write_spec(tmp_path), tmp_path / "report.json")

    assert report["summary"]["config_file_counts"] == {"floorplan_ecc.json": 48}
    assert report["summary"]["config_files_by_strategy"]["grid"] == ["floorplan_ecc.json"]
    assert report["summary"]["strategy_separation"] == {
        "status": "converged",
        "separated_designs": [],
        "converged_designs": [f"design-{index}" for index in range(6)],
        "unknown_designs": [],
    }
    assert report["summary"]["search_space_coverage"]["status"] == "boundary_limited"
    assert report["summary"]["search_space_coverage"]["boundary_axes"] == ["floorplan.core_util"]
    assert report["summary"]["search_space_coverage"]["axes"]["floorplan.core_util"] == {
        "lower_bound": 0.3,
        "upper_bound": 0.4,
        "selected_values": [0.3],
        "lower_boundary_selections": 48,
        "upper_boundary_selections": 0,
        "interior_selections": 0,
        "status": "lower_boundary",
    }
    assert report["runs"][0]["config_files"] == ["floorplan_ecc.json"]


def test_d4_cli_returns_unknown_exit_code_without_enough_designs(tmp_path):
    result = CliRunner().invoke(
        app,
        [
            "experience",
            "dse",
            "d4",
            "--spec",
            str(_write_spec(tmp_path, designs=5)),
            "--output",
            str(tmp_path / "report.json"),
            "--json",
        ],
    )

    assert result.exit_code == 7, result.output
    assert json.loads(result.stdout)[0]["status"] == "unknown"


def test_d4_resource_summary_keeps_partial_scope_and_maximum_trial_rss():
    observation = {
        "peak_rss_bytes": 2048,
        "sample_count": 10,
        "scope": "shared_process_tree",
        "measurement": {"scope": "shared_process_tree", "status": "partial"},
        "host": {"load_average": [12.0, 8.0, 4.0], "logical_cores": 32},
        "host_id": "host-a",
        "outcome": {"status": "success"},
    }
    summary = _summarize_resources(
        [
            {
                "candidate_id": "candidate-1",
                "case_id": "case-1",
                "observations": [
                    {"step": "Synthesis", "observation": {**observation, "peak_rss_bytes": 1024}},
                    {"step": "place", "observation": observation},
                ],
            }
        ],
        source="case_observation",
    )

    assert summary["status"] == "partial"
    assert summary["peak_rss_bytes"] == 2048
    assert summary["peak_rss_scope"] == "max_of_step_observations"
    assert summary["load_1m"]["p50"] == 12.0
    assert summary["scope_counts"] == {"shared_process_tree": 2}
    assert summary["measurement_status_counts"] == {"partial": 2}
    assert summary["coverage"]["rss_observation_ratio"] == 1.0


def test_d4_resource_evidence_does_not_trust_result_only_resources():
    plan = {"schema": "ecc-experience-stage-dse-plan/2"}
    result = {
        "trials": [
            {
                "candidate_id": "candidate-1",
                "resources": [{"observation": {"peak_rss_bytes": 123}}],
            }
        ]
    }

    evidence = _resource_evidence(plan, result)

    assert evidence["status"] == "unknown"
    assert evidence["source"] == "none"
    assert evidence["peak_rss_bytes"] is None


def test_d4_warm_start_evidence_distinguishes_cross_design_seeds():
    evidence = _warm_start_evidence(
        {
            "release_id": "release-a",
            "warm_start": {
                "experimental_cross_design": True,
                "family_isolation": "explicit_groups",
                "seeds": [
                    {"case_id": "case-a", "confidence": "experimental"},
                    {"case_id": "case-b", "confidence": "experimental"},
                ],
            },
        }
    )

    assert evidence == {
        "status": "cross_design",
        "experimental_cross_design": True,
        "seed_count": 2,
        "cross_design_seed_count": 2,
        "family_isolation": "explicit_groups",
        "release_id": "release-a",
    }
