import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.api import study_evaluate, study_publish
from ecc_experience.collection.collect import collect_committed_case
from ecc_experience.knowledge.release import create_release
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import ExperienceError
from ecc_experience.study.evidence import result_cost


@pytest.fixture
def study(workspace_factory, tmp_path):
    repository = ExperienceStore(tmp_path / "store")

    def create(
        name,
        *,
        rtl="heldout",
        score=90.0,
        state="Success",
        sdc="constraints",
        checklist="pass",
        process="selected",
        runtime="version",
        qor=True,
    ):
        workspace = workspace_factory(name)
        source = workspace / "input.v"
        source.write_text(rtl)
        path = workspace / "home/engineering-snapshot.json"
        snapshot = json.loads(path.read_text())
        snapshot["workspaceSpec"] = {
            "design": {"topModule": "sample"},
            "pdk": {"familyId": "ics55"},
            "flow": {"flowId": "test"},
            "parameters": {"floorplan.core_util": 0.3},
            "inputs": [{"inputId": "rtl", "role": "rtl"}],
        }
        snapshot["workspaceBindings"] = {"inputs": {"rtl": str(source)}}
        snapshot["flow"]["steps"][0].update(state=state, checklist_status={"status": "passed"})
        snapshot["checklist"] = {"items": [{"state": checklist, "blocked": checklist == "fail"}]}
        snapshot["signoffAssessment"] = {"status": "ready"}
        snapshot["qorSnapshotExtension"].update(
            status="available" if qor else "unavailable",
            score=score if qor else None,
            feasibility={"status": "PASS", "gates": []},
        )
        if qor:
            snapshot["qorSnapshotExtension"].pop("reason")
        snapshot["artifacts"][0].update(kind="qor_metrics", stepId="Synthesis")
        path.write_text(json.dumps(snapshot))
        (workspace / "home/flow.json").write_text(json.dumps(snapshot["flow"]))
        (workspace / "Synthesis_yosys/analysis/qor_metrics.json").write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "step": "Synthesis",
                    "tool": "yosys",
                    "status": "success",
                    "integrity": {"status": "pass"},
                    "analysis_revision": "revision",
                    "context": {"timing_constraints": {"sdc_sha256": sdc}},
                    "metrics": [
                        {"id": "cells", "value": 10, "unit": "count", "category": "area_cost"}
                    ],
                }
            )
        )
        context = {
            "schema": "ecc-experience-execution-context/1",
            "attempt_id": name,
            "process": {"status": "available", "fingerprint": process},
            "runtime": {
                "ecc": "test",
                "sources": {"chipcompiler": "source"},
                "native_packages": {},
                "tools": {"yosys": runtime},
            },
        }
        return collect_committed_case(
            workspace,
            repository,
            read_workspace_observation,
            attempt_id=name,
            execution_context=context,
        ).case

    training = create("training", rtl="training")
    release = tmp_path / "K.json"
    create_release([training.case_id], repository.root, release)
    baseline = create("baseline", score=80.0)
    candidate = create("candidate", score=90.0)
    feedback = create("feedback", rtl="training")
    spec = {
        "schema_version": 1,
        "release": "K.json",
        "groups": {
            training.case_id: "training",
            baseline.case_id: "heldout",
            candidate.case_id: "heldout",
            feedback.case_id: "training",
        },
        "pairs": [
            {
                "pair_id": "comparison",
                "baseline_case_id": baseline.case_id,
                "candidate_case_id": candidate.case_id,
            }
        ],
        "feedback_case_ids": [feedback.case_id],
    }
    spec_path = tmp_path / "study.json"
    spec_path.write_text(json.dumps(spec))
    return {
        "create": create,
        "repository": repository,
        "spec": spec,
        "path": spec_path,
        "release": release,
        "baseline": baseline,
        "candidate": candidate,
        "feedback": feedback,
        "training": training,
    }


def evaluate(study, name="evaluation.json"):
    study["path"].write_text(json.dumps(study["spec"]))
    return study_evaluate(study["path"], study["repository"].root, study["path"].parent / name)


def test_isolated_feedback_release_excludes_heldout_and_preserves_k(study):
    before = study["release"].read_bytes()
    report = evaluate(study)
    assert report["status"] == "pass"
    assert report["summary"]["mean_score_delta_per_design"] == 10
    assert report["summary"]["independent_heldout_input_count"] == 1
    assert report["generalization_status"] == "unproven"
    assert report["summary"]["controlled_budget_pairs"] == 0
    target = study["path"].parent / "K-plus-1.json"
    result = study_publish(
        study["path"].parent / "evaluation.json", study["repository"].root, target
    )
    assert result["heldout_cases_included"] is False
    assert {item["case_id"] for item in json.loads(target.read_text())["cases"]} == {
        study["training"].case_id,
        study["feedback"].case_id,
    }
    assert study["release"].read_bytes() == before


@pytest.mark.parametrize("kind", ["input", "family", "feedback"])
def test_leakage_cannot_be_hidden_by_case_or_group_aliases(study, kind):
    if kind == "input":
        alias = study["create"]("alias", rtl="training")
        study["spec"]["pairs"][0]["baseline_case_id"] = alias.case_id
        study["spec"]["groups"][alias.case_id] = "heldout"
    elif kind == "family":
        for case in (study["baseline"], study["candidate"]):
            study["spec"]["groups"][case.case_id] = "training"
    else:
        study["spec"]["feedback_case_ids"] = [study["candidate"].case_id]
    report = evaluate(study)
    assert report["status"] == "fail"
    assert report["exit_code"] == 6
    with pytest.raises(ExperienceError, match="passing evaluation"):
        study_publish(
            study["path"].parent / "evaluation.json",
            study["repository"].root,
            study["path"].parent / "next.json",
        )


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"state": "Error"}, "fail"),
        ({"state": "Idle"}, "unknown"),
        ({"qor": False}, "unknown"),
        ({"checklist": "fail"}, "fail"),
        ({"sdc": "different"}, "unknown"),
        ({"process": "different"}, "unknown"),
        ({"runtime": "different"}, "unknown"),
    ],
)
def test_failed_unknown_and_incompatible_trials_remain_in_denominator(study, change, expected):
    case = study["create"]("changed", **change)
    study["spec"]["groups"][case.case_id] = "heldout"
    study["spec"]["pairs"][0]["candidate_case_id"] = case.case_id
    report = evaluate(study)
    assert report["status"] == expected
    assert report["summary"]["pair_count"] == 1
    assert report["summary"]["passed_pairs"] == 0


def test_repeats_do_not_increase_independent_design_or_family_counts(study):
    study["spec"]["pairs"].append({**study["spec"]["pairs"][0], "pair_id": "repeat"})
    report = evaluate(study)
    assert report["summary"]["pair_count"] == 2
    assert report["summary"]["independent_heldout_input_count"] == 1
    assert report["summary"]["heldout_group_count"] == 1
    assert report["summary"]["per_group"]["heldout"]["mean_score_delta_per_design"] == 10


def test_missing_groups_and_unknown_cases_do_not_pass(study):
    del study["spec"]["groups"][study["candidate"].case_id]
    assert evaluate(study)["status"] == "unknown"
    study["spec"]["pairs"].append(
        {
            "pair_id": "missing",
            "baseline_case_id": "case-" + "0" * 64,
            "candidate_case_id": study["candidate"].case_id,
        }
    )
    report = evaluate(study, "second.json")
    assert report["summary"]["pair_count"] == 2
    assert report["pairs"][1]["status"] == "unknown"


def receipt(path, case, *, max_trials=3, elapsed=10):
    path.write_text(
        json.dumps(
            {
                "schema": "ecc-experience-stage-dse-result/1",
                "status": "complete",
                "exit_code": 0,
                "limits": {
                    "max_trials": max_trials,
                    "max_seconds": 60,
                    "trial_timeout_seconds": 20,
                },
                "trials": [{"run_id": "screen-" + case.case_id, "status": "failed"}],
                "full_validation": {"run_id": "full-" + case.case_id, "status": "passed"},
                "fresh_validation": {
                    "run_id": case.source.attempt_id,
                    "case_id": case.case_id,
                    "workspace": case.source.workspace_root,
                    "status": "passed",
                },
                "elapsed_seconds": elapsed,
            }
        )
    )


def test_costs_include_search_failures_and_require_equal_bound_budgets(study):
    root = study["path"].parent
    first, second = root / "baseline-result.json", root / "candidate-result.json"
    receipt(first, study["baseline"], elapsed=30)
    receipt(second, study["candidate"], elapsed=20)
    study["spec"]["pairs"][0].update(baseline_result=first.name, candidate_result=second.name)
    report = evaluate(study)
    pair = report["pairs"][0]
    assert pair["cost_comparison"] == "equal_recorded_budgets"
    assert pair["elapsed_delta_seconds"] == -10
    assert pair["costs"]["candidate"]["failed_or_unknown_trials"] == 1
    receipt(second, study["candidate"], max_trials=4)
    assert evaluate(study, "unequal.json")["summary"]["controlled_budget_pairs"] == 0
    payload = json.loads(second.read_text())
    payload["fresh_validation"]["run_id"] = "unbound"
    second.write_text(json.dumps(payload))
    assert result_cost(second, study["candidate"])["status"] == "unknown"


@pytest.mark.parametrize("change", ["report", "spec", "source", "receipt"])
def test_publish_rechecks_all_bound_evidence(study, change):
    root = study["path"].parent
    first, second = root / "baseline-result.json", root / "candidate-result.json"
    receipt(first, study["baseline"])
    receipt(second, study["candidate"])
    study["spec"]["pairs"][0].update(baseline_result=first.name, candidate_result=second.name)
    evaluate(study)
    report = root / "evaluation.json"
    if change == "report":
        payload = json.loads(report.read_text())
        payload["status"] = "fail"
        report.write_text(json.dumps(payload))
    elif change == "spec":
        study["spec"]["feedback_case_ids"] = []
        study["path"].write_text(json.dumps(study["spec"]))
    elif change == "source":
        (
            Path(study["candidate"].source.workspace_root)
            / "Synthesis_yosys/analysis/qor_metrics.json"
        ).write_text("{}")
    else:
        receipt(second, study["candidate"], elapsed=11)
    with pytest.raises(ExperienceError):
        study_publish(report, study["repository"].root, root / "next.json")
    assert not (root / "next.json").exists()


def test_cli_statuses_and_immutable_outputs(study):
    root = study["path"].parent
    runner = CliRunner()
    args = [
        "experience",
        "study",
        "evaluate",
        "--spec",
        str(study["path"]),
        "--store",
        str(study["repository"].root),
        "--output",
        str(root / "report.json"),
        "--json",
    ]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["status"] == "pass"
    assert runner.invoke(app, args).exit_code == 2
    study["spec"]["groups"].pop(study["candidate"].case_id)
    study["path"].write_text(json.dumps(study["spec"]))
    args[args.index("--output") + 1] = str(root / "unknown.json")
    assert runner.invoke(app, args).exit_code == 7
    publish = [
        "experience",
        "study",
        "publish",
        "--evaluation",
        str(root / "report.json"),
        "--store",
        str(study["repository"].root),
        "--output",
        str(root / "next.json"),
        "--json",
    ]
    assert runner.invoke(app, publish).exit_code == 21


def test_no_feedback_or_reused_attempt_cannot_publish(study):
    study["spec"]["feedback_case_ids"] = []
    evaluate(study)
    with pytest.raises(ExperienceError, match="feedback"):
        study_publish(
            study["path"].parent / "evaluation.json",
            study["repository"].root,
            study["path"].parent / "next.json",
        )
    study["spec"]["pairs"][0]["candidate_case_id"] = study["baseline"].case_id
    assert evaluate(study, "reuse.json")["status"] == "fail"


def test_collection_before_k_freeze_is_not_a_heldout_evaluation(study):
    replacement = study["path"].parent / "later-K.json"
    create_release([study["training"].case_id], study["repository"].root, replacement)
    study["spec"]["release"] = replacement.name
    report = evaluate(study)
    assert "heldout_not_collected_after_release_freeze" in report["pairs"][0]["reasons"]
    assert report["exit_code"] == 6


def test_missing_cost_receipts_do_not_erase_qor_comparison(study):
    study["spec"]["pairs"][0].update(
        baseline_result="missing-baseline.json", candidate_result="missing-candidate.json"
    )
    report = evaluate(study)
    assert report["status"] == "pass"
    assert report["summary"]["mean_score_delta_per_design"] == 10
    assert report["summary"]["controlled_budget_pairs"] == 0


@pytest.mark.parametrize("target", ["store", "source"])
def test_reports_cannot_pollute_source_or_evidence_store(study, target):
    destination = (
        study["repository"].root
        if target == "store"
        else Path(study["candidate"].source.workspace_root)
    )
    with pytest.raises(ExperienceError, match="outside"):
        study_evaluate(study["path"], study["repository"].root, destination / "report.json")
    assert not (destination / "report.json").exists()
