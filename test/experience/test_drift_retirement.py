import json

from ecc_experience.knowledge.drift import assess_drift


def test_drift_keeps_evidence_but_downgrades_and_retires(tmp_path):
    path = tmp_path / "drift.json"
    path.write_text(
        json.dumps(
            {
                "schema": "ecc-experience-drift-observation/1",
                "baseline": {"mae": 0.5, "coverage": 0.9},
                "current": {"mae": 1.0, "coverage": 0.7},
                "thresholds": {"mae": 0.5, "coverage": 0.1},
                "keep_rules": ["rule-shared"],
                "retire_rules": ["rule-old-workaround"],
            }
        )
    )

    result = assess_drift(path, tmp_path / "report.json")

    assert result["status"] == "drift"
    assert result["policy"]["historical_evidence_preserved"] is True
    actions = {item["rule_id"]: item["action"] for item in result["actions"]}
    assert actions["rule-shared"] == "downgrade_to_experimental"
    assert actions["rule-old-workaround"] == "retired"
    assert result["safe_to_apply"] is False


def test_missing_drift_metric_is_unknown(tmp_path):
    path = tmp_path / "drift.json"
    path.write_text(
        json.dumps(
            {
                "schema": "ecc-experience-drift-observation/1",
                "baseline": {"mae": 0.5, "coverage": 0.9},
                "current": {"mae": 0.5},
                "thresholds": {"mae": 0.5, "coverage": 0.1},
            }
        )
    )

    result = assess_drift(path, tmp_path / "report.json")

    assert result["status"] == "unknown"
