import json

from typer.testing import CliRunner

from chipcompiler.cli.app import app
from ecc_experience.api import d4_evaluate
from ecc_experience.benchmark.d4 import (
    _resource_acceptance,
    _resource_evidence,
    _search_space_summary,
    _summarize_resources,
    _warm_start_evidence,
)
from ecc_experience.benchmark.separation import analyze_strategy_separation

STRATEGIES = ("grid", "adaptive", "adaptive_warm", "model_assisted")


def _plan(strategy, design, family, root=None):
    warm = (
        [{"case_id": f"warm-{design}", "confidence": "experimental"}]
        if strategy == "adaptive_warm"
        else []
    )
    payload = {
        "schema": "ecc-experience-stage-dse-plan/2",
        "plan_fingerprint": f"plan-{strategy}-{design}-{family}",
        "strategy": "grid" if strategy == "grid" else "adaptive",
        "input_content_fingerprint": f"input-{design}",
        "process": {"status": "available", "fingerprint": "process"},
        "runtime": {"ecc": "test"},
        "baseline_case_id": f"baseline-{design}",
        "release_id": "release-test",
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
    if warm and root is not None:
        payload["warm_start"]["release"] = str(root / "release.json")
        payload["warm_start"]["groups"] = str(root / "groups.json")
    return payload


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
                **(
                    {
                        "model_prediction": {
                            "status": "available",
                            "prediction": {
                                "prediction": score,
                                "lower_bound": score - 1,
                                "upper_bound": score + 1,
                                "interval": {
                                    "basis": "held_out_grouped_calibration",
                                    "target_coverage": 0.9,
                                },
                            },
                        }
                    }
                    if strategy == "model_assisted"
                    else {}
                ),
            }
            for index in range(2)
        ],
        "full_validation": {"status": "passed", "qor_score": score},
        "fresh_validation": {"status": "passed", "qor_score": score},
        "selection": {"candidate": "candidate-0", "rule": "single_objective"},
    }


def _write_spec(tmp_path, *, designs=6, seeds=2, strategies=STRATEGIES):
    runs = []
    families = ("arithmetic", "memory", "control")
    release_cases = []
    groups = {}
    for design_index in range(designs):
        design = f"design-{design_index}"
        release_cases.extend(
            [
                {
                    "case_id": f"baseline-{design}",
                    "design_fingerprint": f"baseline-design-{design}",
                    "input_content_fingerprint": f"input-{design}",
                    "process_fingerprint": "process",
                },
                {
                    "case_id": f"warm-{design}",
                    "design_fingerprint": f"warm-design-{design}",
                    "input_content_fingerprint": f"warm-input-{design}",
                    "process_fingerprint": "process",
                },
            ]
        )
        groups[f"baseline-{design}"] = f"eval-{design}"
        groups[f"warm-{design}"] = f"train-{design}"
    (tmp_path / "release.json").write_text(
        json.dumps(
            {
                "schema": "ecc-experience-release/1",
                "release_id": "release-test",
                "cases": release_cases,
            }
        )
    )
    (tmp_path / "groups.json").write_text(json.dumps({"schema_version": 1, "cases": groups}))
    for design_index in range(designs):
        design = f"design-{design_index}"
        family = families[design_index % len(families)]
        for seed in range(seeds):
            for order, strategy in enumerate(strategies):
                plan = _plan(strategy, design, family, tmp_path)
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
                        "order": (len(strategies) - 1 - order if seed % 2 else order),
                        "host_class": "test-host",
                        "plan": plan_path.name,
                        "result": result_path.name,
                    }
                )
    spec = tmp_path / "d4.json"
    spec.write_text(json.dumps({"schema": "ecc-experience-d4-spec/1", "runs": runs}))
    return spec


def _write_omission_evidence(
    tmp_path,
    *,
    omitted=None,
    reason="model gates failed",
    evaluation_status="unknown",
    model_release=None,
):
    path = tmp_path / "omission-evidence.json"
    path.write_text(
        json.dumps(
            {
                "evaluation_status": evaluation_status,
                "model_release": model_release,
                "omitted_strategies": ["model_assisted"] if omitted is None else omitted,
                "omitted_reason": reason,
            }
        )
    )
    return path


def test_d4_requires_multi_design_family_and_seed_evidence(tmp_path):
    report = d4_evaluate(_write_spec(tmp_path), tmp_path / "report.json")

    assert report["status"] == "pass"
    assert report["generalization_status"] == "validated_for_declared_scope"
    assert report["summary"]["design_count"] == 6
    assert report["summary"]["family_count"] == 3
    assert report["summary"]["seed_count"] == 2
    assert report["safe_to_apply"] is False
    assert report["promotion_allowed"] is True


def test_d4_accepts_an_explicitly_omitted_optional_model_arm(tmp_path):
    spec = _write_spec(tmp_path, strategies=STRATEGIES[:-1])
    evidence = _write_omission_evidence(tmp_path)

    report = d4_evaluate(spec, tmp_path / "report.json", omission_evidence=evidence)

    assert report["status"] == "pass"
    assert report["summary"]["included_strategies"] == list(STRATEGIES[:-1])
    assert report["summary"]["omitted_strategies"] == ["model_assisted"]
    assert set(report["strategies"]) == set(STRATEGIES[:-1])
    assert [item["strategy"] for item in report["comparisons"]] == [
        "adaptive",
        "adaptive_warm",
    ]
    assert report["summary"]["model_calibration"]["status"] == "unknown"
    assert report["omission_evidence"]["path"] == str(evidence.resolve())
    assert len(report["omission_evidence"]["sha256"]) == 64
    assert report["omission_evidence"]["reason"] == "model gates failed"


def test_d4_rejects_an_unexplained_missing_optional_model_arm(tmp_path):
    report = d4_evaluate(
        _write_spec(tmp_path, strategies=STRATEGIES[:-1]),
        tmp_path / "report.json",
    )

    assert report["status"] == "unknown"
    assert "optional_strategy_omission_unproven:model_assisted" in report["reasons"]
    assert not any(reason.startswith("strategy_missing:") for reason in report["reasons"])


def test_d4_rejects_omission_evidence_that_contradicts_the_run_matrix(tmp_path):
    evidence = _write_omission_evidence(tmp_path)

    report = d4_evaluate(
        _write_spec(tmp_path),
        tmp_path / "report.json",
        omission_evidence=evidence,
    )

    assert report["status"] == "unknown"
    assert "optional_strategy_omission_mismatch" in report["reasons"]


def test_d4_rejects_omission_evidence_that_claims_a_working_model(tmp_path):
    evidence = _write_omission_evidence(
        tmp_path,
        evaluation_status="pass",
        model_release="model-release.json",
    )

    report = d4_evaluate(
        _write_spec(tmp_path, strategies=STRATEGIES[:-1]),
        tmp_path / "report.json",
        omission_evidence=evidence,
    )

    assert report["status"] == "unknown"
    assert "omission_evidence_claims_a_model_release" in report["reasons"]
    assert "omission_evidence_claims_model_pass" in report["reasons"]


def test_d4_summarizes_selection_conditioned_model_calibration(tmp_path):
    report = d4_evaluate(_write_spec(tmp_path), tmp_path / "report.json")

    calibration = report["summary"]["model_calibration"]
    assert calibration["status"] == "available"
    assert calibration["selection_conditioned"] is True
    assert calibration["pair_count"] == 12
    assert calibration["design_count"] == 6
    assert calibration["family_count"] == 3
    assert calibration["mae"] == 0.0
    assert calibration["interval"] == {
        "status": "available",
        "design_count": 6,
        "observation_count": 12,
        "covered_count": 12,
        "observed_coverage": 1.0,
        "target_coverage": 0.9,
    }
    model_row = next(row for row in report["runs"] if row["strategy"] == "model_assisted")
    assert model_row["model_metrics"]["post_selection"] == {
        "status": "available",
        "candidate_id": "candidate-0",
        "predicted_final_qor": 90.0,
        "observed_final_qor": 90.0,
        "residual": 0.0,
        "absolute_residual": 0.0,
        "interval_status": "available",
        "lower_bound": 89.0,
        "upper_bound": 91.0,
        "covered": True,
        "target_coverage": 0.9,
        "basis": "held_out_grouped_calibration",
    }


def test_d4_tolerates_a_malformed_prediction_interval(tmp_path):
    spec = _write_spec(tmp_path)
    result_path = tmp_path / "design-0-0-model_assisted-result.json"
    result = json.loads(result_path.read_text())
    for trial in result["trials"]:
        trial["model_prediction"]["prediction"]["interval"] = []
    result_path.write_text(json.dumps(result))

    report = d4_evaluate(spec, tmp_path / "report.json")

    row = next(
        item
        for item in report["runs"]
        if item["design"] == "design-0" and item["strategy"] == "model_assisted"
    )
    assert row["model_metrics"]["post_selection"]["interval_status"] == "available"
    assert row["model_metrics"]["post_selection"]["target_coverage"] is None
    assert row["model_metrics"]["post_selection"]["basis"] is None


def test_d4_does_not_claim_interval_calibration_from_one_design(tmp_path):
    spec = _write_spec(tmp_path)
    for design_index in range(1, 6):
        for seed in range(2):
            result_path = tmp_path / f"design-{design_index}-{seed}-model_assisted-result.json"
            result = json.loads(result_path.read_text())
            for trial in result["trials"]:
                prediction = trial["model_prediction"]["prediction"]
                prediction.pop("lower_bound")
                prediction.pop("upper_bound")
            result_path.write_text(json.dumps(result))

    report = d4_evaluate(spec, tmp_path / "report.json")

    calibration = report["summary"]["model_calibration"]
    assert calibration["status"] == "available"
    assert calibration["interval"] == {
        "status": "insufficient_evidence",
        "design_count": 1,
        "observation_count": 2,
        "covered_count": 2,
        "observed_coverage": 1.0,
        "target_coverage": 0.9,
    }


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


def test_d4_requires_full_and_fresh_validation_to_pass(tmp_path):
    spec = _write_spec(tmp_path)
    result_path = tmp_path / "design-0-0-grid-result.json"
    result = json.loads(result_path.read_text())
    result["full_validation"]["status"] = "failed"
    result["fresh_validation"] = {"status": "failed"}
    result_path.write_text(json.dumps(result))

    report = d4_evaluate(spec, tmp_path / "report.json")

    assert report["status"] == "unknown"
    assert "full_validation_not_passed:design-0" in report["reasons"]
    assert "fresh_validation_not_passed:design-0" in report["reasons"]
    assert "final_qor_unavailable:design-0" in report["reasons"]


def test_d4_requires_resource_evidence_when_a_store_is_declared(tmp_path):
    spec = _write_spec(tmp_path)
    plan_path = tmp_path / "design-0-0-grid-plan.json"
    plan = json.loads(plan_path.read_text())
    plan["store"] = str(tmp_path / "missing-store")
    plan_path.write_text(json.dumps(plan))

    report = d4_evaluate(spec, tmp_path / "report.json")

    assert report["status"] == "unknown"
    assert "resource_evidence_unavailable:design-0" in report["reasons"]
    assert "host_load_evidence_unavailable:design-0" in report["reasons"]


def test_d4_rejects_a_loaded_model_without_available_predictions(tmp_path):
    spec = _write_spec(tmp_path)
    result_path = tmp_path / "design-0-0-model_assisted-result.json"
    result = json.loads(result_path.read_text())
    for trial in result["trials"]:
        trial.pop("model_prediction")
    result_path.write_text(json.dumps(result))

    report = d4_evaluate(spec, tmp_path / "report.json")

    assert report["status"] == "unknown"
    assert "model_evidence_unavailable:design-0" in report["reasons"]
    row = next(
        item
        for item in report["runs"]
        if item["design"] == "design-0" and item["strategy"] == "model_assisted"
    )
    assert row["model_metrics"]["status"] == "available"
    assert row["model_metrics"]["prediction_count"] == 0
    assert row["model_metrics"]["post_selection"] == {
        "status": "unknown",
        "reason": "selected_prediction_unavailable",
        "candidate_id": "candidate-0",
    }


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
        "comparison_unit": "design_seed_strategy",
        "separated_designs": [],
        "converged_designs": [f"design-{index}" for index in range(6)],
        "unstable_designs": [],
        "unknown_designs": [],
        "seed_groups": [
            {
                "design": f"design-{design_index}",
                "seed": seed,
                "status": "converged",
                "strategy_count": 4,
                "distinct_selections": 1,
            }
            for design_index in range(6)
            for seed in range(2)
        ],
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


def test_strategy_separation_compares_within_each_seed():
    rows = []
    for seed in (0, 1):
        for index, strategy in enumerate(STRATEGIES):
            rows.append(
                {
                    "design": "design-a",
                    "seed": seed,
                    "strategy": strategy,
                    "status": "complete",
                    "selected_parameters": {"core_util": index if seed == 0 else 0.4},
                }
            )

    result = analyze_strategy_separation(rows, STRATEGIES)

    assert result == {
        "status": "unknown",
        "comparison_unit": "design_seed_strategy",
        "separated_designs": [],
        "converged_designs": [],
        "unstable_designs": ["design-a"],
        "unknown_designs": [],
        "seed_groups": [
            {
                "design": "design-a",
                "seed": 0,
                "status": "separated",
                "strategy_count": 4,
                "distinct_selections": 4,
            },
            {
                "design": "design-a",
                "seed": 1,
                "status": "converged",
                "strategy_count": 4,
                "distinct_selections": 1,
            },
        ],
    }


def test_search_space_reports_incomplete_cartesian_coverage():
    runs = []
    for strategy in STRATEGIES:
        runs.append(
            {
                "design": "design-a",
                "strategy": strategy,
                "seed": 1,
                "plan": {
                    "space": {
                        "core_util": [0.4, 0.44, 0.48],
                        "density": [0.2, 0.25, 0.3],
                        "hold_margin": [0.0, 0.02, 0.04],
                    },
                    "limits": {"max_trials": 16},
                },
                "result": {"selection": {"candidate": "candidate-0"}, "trials": []},
            }
        )

    result = _search_space_summary(runs)

    assert result["cartesian_coverage"] == {
        "status": "budget_limited",
        "declared_combination_counts": [27],
        "trial_budget_limits": [16],
        "required_trial_budgets": [29],
        "budget_limited_runs": sorted(f"design-a:{strategy}:1" for strategy in STRATEGIES),
        "missing_budget_runs": [],
        "limitation": (
            "The Cartesian grid must fit max_trials after reserving rung promotions and "
            "two independent full/fresh validations; otherwise the grid cannot be treated "
            "as fully explored"
        ),
    }


def test_search_space_counts_promotions_and_validations_before_claiming_coverage():
    ready = {
        "space": {
            "core_util": [0.4, 0.44, 0.48],
            "density": [0.2, 0.25, 0.3],
            "hold_margin": [0.0, 0.02, 0.04],
        },
        "limits": {"max_trials": 31},
        "screening_trials": 27,
        "rungs": [
            {"through_step": "place", "promote_count": 2},
            {"through_step": "Timing optimization", "promote_count": 1},
        ],
    }
    run = {
        "design": "design-a",
        "strategy": "grid",
        "seed": 1,
        "plan": ready,
        "result": {"selection": {"candidate": "candidate-0"}, "trials": []},
    }
    assert _search_space_summary([run])["cartesian_coverage"]["status"] == "complete"

    run["plan"] = {**ready, "limits": {"max_trials": 27}}
    coverage = _search_space_summary([run])["cartesian_coverage"]
    assert coverage["status"] == "budget_limited"
    assert coverage["required_trial_budgets"] == [31]


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


def test_d4_cli_accepts_explicit_optional_strategy_omission(tmp_path):
    result = CliRunner().invoke(
        app,
        [
            "experience",
            "dse",
            "d4",
            "--spec",
            str(_write_spec(tmp_path, strategies=STRATEGIES[:-1])),
            "--omission-evidence",
            str(_write_omission_evidence(tmp_path)),
            "--output",
            str(tmp_path / "report.json"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)[0]
    assert report["status"] == "pass"
    assert report["summary"]["omitted_strategies"] == ["model_assisted"]


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


def test_d4_resource_acceptance_requires_load_without_hiding_partial_scope():
    run = {
        "design": "design-a",
        "strategy": "grid",
        "seed": 1,
        "plan": {"store": "/store"},
    }
    complete = _resource_acceptance(
        [
            {
                "design": "design-a",
                "strategy": "grid",
                "seed": 1,
                "resources": {"observation_count": 2},
                "observed_load_average": [4.0, 3.0, 2.0],
            }
        ],
        [run],
    )
    partial = _resource_acceptance(
        [
            {
                "design": "design-a",
                "strategy": "grid",
                "seed": 1,
                "resources": {"observation_count": 2},
                "observed_load_average": None,
            }
        ],
        [run],
    )

    assert complete["status"] == "complete"
    assert complete["run_ratio"] == 1.0
    assert complete["host_load_ratio"] == 1.0
    assert partial["status"] == "partial"
    assert partial["host_load_ratio"] == 0.0
    assert "shared_process_tree" in complete["measurement_scope"]


def test_d4_warm_start_evidence_distinguishes_cross_design_seeds(tmp_path):
    (tmp_path / "release.json").write_text(
        json.dumps(
            {
                "schema": "ecc-experience-release/1",
                "release_id": "release-a",
                "cases": [
                    {
                        "case_id": "baseline",
                        "design_fingerprint": "design-query",
                        "input_content_fingerprint": "input-query",
                        "process_fingerprint": "process-a",
                    },
                    {
                        "case_id": "case-a",
                        "design_fingerprint": "design-a",
                        "input_content_fingerprint": "input-a",
                        "process_fingerprint": "process-a",
                    },
                    {
                        "case_id": "case-b",
                        "design_fingerprint": "design-b",
                        "input_content_fingerprint": "input-b",
                        "process_fingerprint": "process-a",
                    },
                ],
            }
        )
    )
    (tmp_path / "groups.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cases": {"baseline": "eval", "case-a": "family-a", "case-b": "family-b"},
            }
        )
    )
    evidence = _warm_start_evidence(
        {
            "release_id": "release-a",
            "baseline_case_id": "baseline",
            "input_content_fingerprint": "input-query",
            "process": {"fingerprint": "process-a"},
            "warm_start": {
                "experimental_cross_design": True,
                "family_isolation": "explicit_groups",
                "release": str(tmp_path / "release.json"),
                "groups": str(tmp_path / "groups.json"),
                "seeds": [
                    {"case_id": "case-a", "confidence": "experimental"},
                    {"case_id": "case-b", "confidence": "experimental"},
                ],
            },
        },
        tmp_path,
    )

    assert evidence == {
        "status": "cross_design",
        "experimental_cross_design": True,
        "seed_count": 2,
        "cross_design_seed_count": 2,
        "family_isolation": "explicit_groups",
        "release_id": "release-a",
        "cross_design_verified": True,
        "cross_design_verification": "release_design_and_group_isolation",
        "baseline_design_fingerprint": "design-query",
        "seed_design_fingerprints": ["design-a", "design-b"],
        "evaluation_group_isolated": True,
    }


def test_d4_warm_start_rejects_seed_from_the_same_design(tmp_path):
    (tmp_path / "release.json").write_text(
        json.dumps(
            {
                "schema": "ecc-experience-release/1",
                "release_id": "release-a",
                "cases": [
                    {
                        "case_id": "baseline",
                        "design_fingerprint": "same-design",
                        "input_content_fingerprint": "input-query",
                        "process_fingerprint": "process-a",
                    },
                    {
                        "case_id": "case-a",
                        "design_fingerprint": "same-design",
                        "input_content_fingerprint": "input-a",
                        "process_fingerprint": "process-a",
                    },
                ],
            }
        )
    )

    evidence = _warm_start_evidence(
        {
            "release_id": "release-a",
            "baseline_case_id": "baseline",
            "input_content_fingerprint": "input-query",
            "process": {"fingerprint": "process-a"},
            "warm_start": {
                "experimental_cross_design": True,
                "family_isolation": "explicit_groups",
                "release": str(tmp_path / "release.json"),
                "groups": str(tmp_path / "groups.json"),
                "seeds": [{"case_id": "case-a", "confidence": "experimental"}],
            },
        },
        tmp_path,
    )

    assert evidence["cross_design_verified"] is False
    assert evidence["cross_design_verification"] == "same_design_fingerprint"
