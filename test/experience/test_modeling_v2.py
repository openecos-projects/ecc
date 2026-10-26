import json

import pytest

from ecc_experience.files import canonical_bytes, digest
from ecc_experience.modeling.model import evaluate_model, publish_model, train_model
from ecc_experience.modeling.predict import read_model_release
from ecc_experience.models import ExperienceError


def _row(index, value, group, *, process="process-a", runtime=None):
    return {
        "case_id": f"case-{index}",
        "input_content_fingerprint": f"input-{index}",
        "group": group,
        "attempt_id": f"attempt-{index}",
        "features": {"constant": 1.0, "spec.utilization": float(value)},
        "target": 100.0 + 2.0 * value,
        "parameters": {"floorplan.core_util": value},
        "process_fingerprint": process,
        "runtime": runtime or {"ecc": "test", "openroad": "2026"},
        "design_fingerprint": f"design-{index}",
        "constraints_fingerprint": "constraints-a",
        "toolchain_fingerprint": "toolchain-a",
        "parameter_evidence_level": "configured",
        "resource_scope": {"steps": []},
        "feature_coverage": {
            "stage": "Synthesis",
            "identity_fields": 4,
            "required_identity_fields": 4,
        },
    }


def _dataset(path, rows):
    identity = {
        "schema": "ecc-experience-model-dataset/2",
        "feature_schema": "ecc-experience-model-features/2",
        "release_id": "release-v2",
        "release_sha256": "sha-v2",
        "target": "final_qor",
        "through_step": "Synthesis",
        "groups": {item["case_id"]: item["group"] for item in rows},
        "rows": rows,
    }
    path.write_bytes(
        canonical_bytes(
            {
                **identity,
                "dataset_id": f"dataset-{digest(identity)}",
                "summary": {"row_count": len(rows)},
                "excluded": [],
                "limitations": [],
            }
        )
    )


def test_v2_evaluation_rejects_family_leakage(tmp_path):
    training = tmp_path / "training.json"
    heldout = tmp_path / "heldout.json"
    _dataset(training, [_row(index, index + 1, f"family-{index % 2}") for index in range(6)])
    _dataset(
        heldout,
        [_row(index + 10, index + 1.5, f"family-{index % 2}") for index in range(4)],
    )
    model = tmp_path / "model.json"
    train_model(training, model)
    with pytest.raises(ExperienceError, match="families overlap") as error:
        evaluate_model(model, heldout)
    assert error.value.code == "experience_model_leakage"


def test_v2_release_carries_verified_metrics_and_scope(tmp_path):
    training = tmp_path / "training.json"
    heldout = tmp_path / "heldout.json"
    _dataset(training, [_row(index, index + 1, f"train-family-{index % 2}") for index in range(6)])
    _dataset(
        heldout,
        [_row(index + 10, index + 1.5, f"heldout-family-{index % 2}") for index in range(4)],
    )
    model = tmp_path / "model.json"
    evaluation = tmp_path / "evaluation.json"
    release = tmp_path / "release.json"
    train_model(training, model)
    report = evaluate_model(model, heldout, evaluation)
    publish_model(model, evaluation, release)

    payload = json.loads(release.read_text())
    assert payload["schema"] == "ecc-experience-model-release/2"
    assert payload["validation"]["metrics"] == report["metrics"]
    assert payload["validation"]["summary"]["independent_input_count"] == 4
    loaded = read_model_release(release)
    assert loaded["validation"]["status"] == "pass"
