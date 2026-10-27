import json

from ecc_experience.knowledge.champion import compare_champion


def _spec(tmp_path, *, challenger_mae=0.8, regression=False):
    payload = {
        "schema": "ecc-experience-champion-spec/1",
        "equal_budget": True,
        "champion": {
            "release_id": "model-release-champion",
            "metrics": {"mae": 1.0, "coverage": 0.9},
            "evidence": {"design_count": 6, "family_count": 3},
        },
        "challenger": {
            "release_id": "model-release-challenger",
            "metrics": {"mae": challenger_mae, "coverage": 0.7 if regression else 0.9},
            "evidence": {"design_count": 6, "family_count": 3},
        },
        "thresholds": {
            "primary_metric": "mae",
            "primary_direction": "minimize",
            "min_improvement": 0.1,
            "max_regressions": {"coverage": 0.05},
            "regression_directions": {"coverage": "maximize"},
        },
    }
    path = tmp_path / "champion.json"
    path.write_text(json.dumps(payload))
    return path


def test_challenger_can_be_selected_for_review_but_not_published(tmp_path):
    result = compare_champion(_spec(tmp_path), tmp_path / "report.json")

    assert result["status"] == "promote_candidate"
    assert result["actions"]["selected"] == "challenger"
    assert result["actions"]["publish_allowed"] is False
    assert result["safe_to_apply"] is False


def test_challenger_regression_retains_champion(tmp_path):
    result = compare_champion(_spec(tmp_path, regression=True), tmp_path / "report.json")

    assert result["status"] == "retain_champion"
    assert result["actions"]["selected"] == "champion"
