import json

import pytest

from ecc_experience.knowledge.bridge import evaluate_bridge
from ecc_experience.models import ExperienceError


def _metric_set(value=0.0):
    return {
        "qor_delta": value,
        "rank_consistency": 0.95,
        "residual_delta": 0.0,
        "interval_coverage_delta": 0.0,
        "search_regret_delta": 0.0,
        "first_feasible_delta_seconds": 0.0,
        "resource_error": 0.1,
    }


def _spec(tmp_path, metrics=None):
    payload = {
        "schema": "ecc-experience-bridge-spec/1",
        "baseline_cohort": "cohort-old",
        "candidate_cohort": "cohort-new",
        "designs": [
            {
                "design": f"design-{index}",
                "family": f"family-{index % 2}",
                "input_fingerprint": f"input-{index}",
                "metrics": metrics or _metric_set(),
            }
            for index in range(3)
        ],
    }
    path = tmp_path / "bridge.json"
    path.write_text(json.dumps(payload))
    return path


def test_bridge_pass_is_review_only(tmp_path):
    result = evaluate_bridge(_spec(tmp_path), tmp_path / "report.json")

    assert result["status"] == "pass"
    assert result["cohort_recommendation"] == "compatible_experimental"
    assert result["promotion_allowed"] is False
    assert result["safe_to_apply"] is False


def test_bridge_missing_metric_stays_unknown(tmp_path):
    metrics = _metric_set()
    metrics.pop("rank_consistency")
    result = evaluate_bridge(_spec(tmp_path, metrics), tmp_path / "report.json")

    assert result["status"] == "unknown"
    assert "bridge_evidence_unknown" in result["reasons"]


def test_bridge_regression_is_fail(tmp_path):
    result = evaluate_bridge(_spec(tmp_path, _metric_set(-1.0)), tmp_path / "report.json")

    assert result["status"] == "fail"
    assert "bridge_regression" in result["reasons"]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("max_qor_regression", -0.1),
        ("min_rank_consistency", 1.1),
        ("min_interval_coverage_delta", -1.1),
        ("max_resource_error", -0.2),
    ],
)
def test_bridge_rejects_invalid_thresholds(tmp_path, key, value):
    path = _spec(tmp_path)
    payload = json.loads(path.read_text())
    payload["thresholds"] = {key: value}
    path.write_text(json.dumps(payload))

    with pytest.raises(ExperienceError, match="Bridge"):
        evaluate_bridge(path, tmp_path / "report.json")
