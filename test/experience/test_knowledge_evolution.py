import json

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from ecc_experience.files import digest
from ecc_experience.knowledge.campaign import (
    CAMPAIGN_MANIFEST_SCHEMA,
    build_campaign_manifest,
    compute_knowledge_delta,
)
from ecc_experience.knowledge.strategy import advise_strategy
from ecc_experience.models import ExperienceError


def _plan(design, strategy):
    return {
        "schema": "ecc-experience-stage-dse-plan/2",
        "plan_fingerprint": f"plan-{design}-{strategy}",
        "strategy": "grid" if strategy == "grid" else "adaptive",
        "runtime": {"ecc": "test", "tools": {"yosys": "0.61"}},
        "process": {"status": "available", "fingerprint": "process-a"},
        "limits": {"max_trials": 4, "max_seconds": 60, "trial_timeout_seconds": 30},
        "screening_trials": 2,
        "rungs": [{"through_step": "Synthesis", "promote_count": 1}],
        "space": {"floorplan.core_util": [0.32, 0.4]},
        "objectives": [{"id": "qor", "direction": "minimize"}],
        "warm_start": {"seeds": []},
    }


def _result(plan, score):
    return {
        "schema": "ecc-experience-stage-dse-result/2",
        "plan_fingerprint": plan["plan_fingerprint"],
        "status": "complete",
        "elapsed_seconds": 10,
        "trials": [
            {
                "candidate_id": "candidate-a",
                "case_id": "case-a",
                "status": "stage_passed",
                "feature_status": "available",
                "config_receipt": {"status": "matched"},
            }
        ],
        "full_validation": {"status": "passed", "qor_score": score, "case_id": "case-full"},
        "fresh_validation": {"status": "passed", "qor_score": score, "case_id": "case-fresh"},
        "model": {"status": "not_requested"},
    }


def _campaign(tmp_path):
    runs = []
    for strategy in ("grid", "adaptive"):
        plan = _plan("design-a", strategy)
        plan_path = tmp_path / f"{strategy}-plan.json"
        result_path = tmp_path / f"{strategy}-result.json"
        plan_path.write_text(json.dumps(plan))
        result_path.write_text(json.dumps(_result(plan, 10)))
        runs.append(
            {
                "design": "design-a",
                "family": "family-a",
                "strategy": strategy,
                "seed": 1,
                "plan": plan_path.name,
                "result": result_path.name,
            }
        )
    spec = tmp_path / "d4-spec.json"
    spec_payload = {"schema": "ecc-experience-d4-spec/1", "runs": runs}
    spec.write_text(json.dumps(spec_payload))
    report = {
        "schema": "ecc-experience-d4-report/1",
        "report_id": "d4-test",
        "status": "unknown",
        "reasons": [],
        "spec": str(spec),
        "spec_fingerprint": digest(spec_payload),
        "summary": {"equal_budget": True, "minimum_designs": 6, "minimum_families": 3},
        "runs": [
            {
                "design": run["design"],
                "strategy": run["strategy"],
                "seed": run["seed"],
                "status": "complete",
                "full_validation": "passed",
                "fresh_validation": "passed",
                "final_qor": 10.0,
            }
            for run in runs
        ],
    }
    report_path = tmp_path / "d4-report.json"
    report_path.write_text(json.dumps(report))
    return report_path


def test_campaign_manifest_stays_candidate_and_delta_requires_heldout(tmp_path):
    report = _campaign(tmp_path)
    manifest = build_campaign_manifest(report, tmp_path / "manifest.json")

    assert manifest["schema"] == CAMPAIGN_MANIFEST_SCHEMA
    assert manifest["mode"] == "candidate"
    assert manifest["safe_to_apply"] is False
    assert manifest["counts"]["candidate_cases"] == 0
    assert manifest["runs"][0]["quality"]["level"] == "medium"

    release = tmp_path / "release.json"
    release.write_text(
        json.dumps(
            {
                "release_id": "model-release-old",
                "model_id": "model-old",
                "validation": {"metrics": {"mae": 1.0}},
            }
        )
    )
    heldout = tmp_path / "heldout.json"
    heldout.write_text(
        json.dumps(
            {
                "schema": "ecc-experience-heldout/1",
                "case_ids": ["case-heldout"],
                "designs": ["design-heldout"],
            }
        )
    )
    delta = compute_knowledge_delta(
        tmp_path / "manifest.json",
        tmp_path / "delta.json",
        previous_release=release,
        heldout=heldout,
    )

    assert delta["status"] == "candidate"
    assert delta["heldout"]["ready"] is False
    assert delta["decisions"]["training_allowed"] is False
    assert delta["decisions"]["promotion_allowed"] is False
    assert delta["model"]["previous_release"]["release_id"] == "model-release-old"
    assert delta["queue"]["rebridge"]


def test_heldout_design_overlap_blocks_training(tmp_path):
    report = _campaign(tmp_path)
    build_campaign_manifest(report, tmp_path / "manifest.json")
    heldout = tmp_path / "heldout.json"
    heldout.write_text(
        json.dumps(
            {
                "schema": "ecc-experience-heldout/1",
                "case_ids": [],
                "designs": ["design-a"],
            }
        )
    )
    delta = compute_knowledge_delta(
        tmp_path / "manifest.json", tmp_path / "delta.json", heldout=heldout
    )

    assert delta["heldout"]["ready"] is False
    assert "design-a" in delta["heldout"]["overlap"]
    assert delta["decisions"]["training_allowed"] is False


def test_campaign_manifest_rejects_stale_spec_fingerprint(tmp_path):
    report = _campaign(tmp_path)
    payload = json.loads(report.read_text())
    payload["spec_fingerprint"] = "stale"
    report.write_text(json.dumps(payload))

    with pytest.raises(ExperienceError, match="fingerprint"):
        build_campaign_manifest(report, tmp_path / "manifest.json")


def test_campaign_manifest_rejects_changed_run_evidence(tmp_path):
    report = _campaign(tmp_path)
    result_path = tmp_path / "grid-result.json"
    payload = json.loads(result_path.read_text())
    payload["status"] = "stopped"
    result_path.write_text(json.dumps(payload))

    with pytest.raises(ExperienceError, match="run evidence"):
        build_campaign_manifest(report, tmp_path / "manifest.json")


def test_strategy_advice_requires_significant_paired_evidence(tmp_path):
    runs = []
    for index in range(6):
        for strategy, score in (("grid", 10.0), ("adaptive", 9.0)):
            runs.append(
                {
                    "design": f"design-{index}",
                    "seed": 1,
                    "strategy": strategy,
                    "final_qor": score,
                    "eligible": True,
                }
            )
    manifest = {
        "schema": CAMPAIGN_MANIFEST_SCHEMA,
        "campaign_id": "campaign-a",
        "mode": "candidate",
        "budget": {"equal_budget": True},
        "runs": runs,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    result = advise_strategy(path, tmp_path / "advice.json")

    assert result["recommended"] == "adaptive"
    assert result["confidence"] == "experimental"
    assert result["promotion_allowed"] is False
    assert result["comparisons"]["adaptive"]["wins"] == 6


def test_knowledge_cli_exposes_candidate_output(tmp_path):
    runs = []
    for index in range(6):
        for strategy, score in (("grid", 10.0), ("adaptive", 9.0)):
            runs.append(
                {
                    "design": f"design-{index}",
                    "seed": 1,
                    "strategy": strategy,
                    "final_qor": score,
                    "eligible": True,
                }
            )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": CAMPAIGN_MANIFEST_SCHEMA,
                "campaign_id": "campaign-a",
                "mode": "candidate",
                "budget": {"equal_budget": True},
                "runs": runs,
            }
        )
    )
    output = tmp_path / "advice.json"

    result = CliRunner().invoke(
        app,
        [
            "experience",
            "knowledge",
            "advice",
            "--manifest",
            str(manifest),
            "--output",
            str(output),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)[0]
    assert payload["recommended"] == "adaptive"
    assert payload["safe_to_apply"] is False
