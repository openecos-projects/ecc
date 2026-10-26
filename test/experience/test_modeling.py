import json

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.collection.collect import collect_committed_case
from ecc_experience.files import canonical_bytes, digest
from ecc_experience.knowledge.release import create_release
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.modeling.dataset import build_dataset
from ecc_experience.modeling.model import evaluate_model, train_model
from ecc_experience.modeling.predict import advise_dataset, read_model_release
from ecc_experience.modeling.registry import promote, rollback, status
from ecc_experience.modeling.validation import validate_matrix
from ecc_experience.models import ExperienceError


def make_dataset(path, rows, *, release_id="release-ics55"):
    identity = {
        "schema": "ecc-experience-model-dataset/1",
        "feature_schema": "ecc-experience-model-features/1",
        "release_id": release_id,
        "release_sha256": f"sha-{release_id}",
        "target": "final_qor",
        "through_step": "Synthesis",
        "groups": {row["case_id"]: row["group"] for row in rows},
        "rows": rows,
    }
    payload = {
        **identity,
        "dataset_id": f"dataset-{digest(identity)}",
        "summary": {"row_count": len(rows)},
        "excluded": [],
        "limitations": [],
    }
    path.write_bytes(canonical_bytes(payload))
    return payload


def row(index, value, group):
    return {
        "case_id": f"case-{index}",
        "input_content_fingerprint": f"input-{index}",
        "group": group,
        "attempt_id": f"attempt-{index}",
        "features": {"constant": 1.0, "spec.utilization": float(value)},
        "target": 100.0 + 2.0 * value,
        "parameters": {"floorplan.core_util": value},
        "process_fingerprint": "ics55-process",
        "runtime": {"ecc": "test", "openroad": "2026"},
    }


@pytest.fixture
def modeling_files(tmp_path):
    training = tmp_path / "training.json"
    heldout = tmp_path / "heldout.json"
    training_rows = [
        row(index, index + 1, "family-a" if index % 2 else "family-b") for index in range(6)
    ]
    heldout_rows = [
        row(index + 10, index + 1.5, "family-a" if index % 2 else "family-b") for index in range(4)
    ]
    make_dataset(training, training_rows, release_id="release-training")
    make_dataset(heldout, heldout_rows, release_id="release-heldout")
    return training, heldout, tmp_path


def test_model_lifecycle_publishes_scope_checked_release_and_advice(modeling_files):
    training, heldout, root = modeling_files
    model_path = root / "model.json"
    evaluation_path = root / "evaluation.json"
    release_path = root / "model-release.json"
    advice_path = root / "advice.json"

    model = train_model(training, model_path)
    assert model["training_summary"]["interval_basis"] == "leave_one_input_out"
    assert model["training_summary"]["cross_validation_folds"] == 6
    assert (
        model["training_summary"]["residual_std"]
        >= model["training_summary"]["in_sample_residual_std"]
    )
    report = evaluate_model(model_path, heldout, evaluation_path, max_mae=10.0)
    assert report["status"] == "pass"
    assert report["generalization_status"] == "validated_for_declared_scope"

    from ecc_experience.modeling.model import publish_model

    published = publish_model(model_path, evaluation_path, release_path)
    assert published["generalization_status"] == "validated_for_declared_scope"
    release = read_model_release(release_path)
    assert release["model_id"] == model["model_id"]

    advice = advise_dataset(release_path, heldout, advice_path, limit=2)
    assert advice["safe_to_apply"] is False
    assert len(advice["candidates"]) == 2
    assert (
        advice["candidates"][0]["prediction"]["prediction"]
        >= advice["candidates"][1]["prediction"]["prediction"]
    )


def test_model_evaluation_rejects_input_leakage(modeling_files):
    training, heldout, root = modeling_files
    model_path = root / "model.json"
    train_model(training, model_path)
    payload = json.loads(heldout.read_text())
    payload["rows"][0]["input_content_fingerprint"] = "input-1"
    identity = {
        key: payload[key]
        for key in (
            "schema",
            "feature_schema",
            "release_id",
            "release_sha256",
            "target",
            "through_step",
            "groups",
            "rows",
        )
    }
    payload["dataset_id"] = f"dataset-{digest(identity)}"
    heldout.write_bytes(canonical_bytes(payload))
    with pytest.raises(ExperienceError, match="overlap") as error:
        evaluate_model(model_path, heldout)
    assert error.value.code == "experience_model_leakage"


def test_model_evaluation_reports_unknown_without_independent_scope(modeling_files):
    training, heldout, root = modeling_files
    model_path = root / "model.json"
    train_model(training, model_path)
    report = evaluate_model(model_path, heldout, min_independent_designs=10)
    assert report["status"] == "unknown"
    assert report["exit_code"] == 7


def test_model_validation_matrix_aggregates_designs_and_families(modeling_files):
    training, heldout, root = modeling_files
    model_path = root / "matrix-model.json"
    train_model(training, model_path)
    heldout_payload = json.loads(heldout.read_text())
    first = root / "design-a.json"
    second = root / "design-b.json"
    for index, item in enumerate(heldout_payload["rows"]):
        item["input_content_fingerprint"] = f"heldout-design-{index // 2}"
        item["group"] = "family-a" if index < 2 else "family-b"
    make_dataset(first, heldout_payload["rows"][:2], release_id="release-design-a")
    make_dataset(second, heldout_payload["rows"][2:], release_id="release-design-b")
    matrix_identity = {
        "schema": "ecc-experience-model-validation-matrix/1",
        "datasets": [
            {"path": first.name, "design": "design-a", "family": "family-a"},
            {"path": second.name, "design": "design-b", "family": "family-b"},
        ],
    }
    matrix_identity["matrix_id"] = f"matrix-{digest(matrix_identity)}"
    matrix = root / "matrix.json"
    matrix.write_bytes(canonical_bytes(matrix_identity))
    report = validate_matrix(
        model_path, matrix, root / "matrix-report.json", min_independent_designs=2
    )
    assert report["status"] == "pass"
    assert report["calibration"]["status"] == "available"
    assert report["calibration"]["cross_validated_group_count"] == 2
    assert report["summary"] == {
        "row_count": 4,
        "independent_input_count": 2,
        "design_count": 2,
        "family_count": 2,
    }
    assert {item["design"] for item in report["designs"]} == {"design-a", "design-b"}
    from ecc_experience.modeling.model import publish_model

    published = publish_model(model_path, root / "matrix-report.json", root / "matrix-release.json")
    assert published["generalization_status"] == "validated_for_declared_scope"
    assert (
        read_model_release(root / "matrix-release.json")["validation"]["calibration"]
        == report["calibration"]
    )


def test_model_registry_promote_status_and_rollback(modeling_files):
    training, heldout, root = modeling_files
    model_one = root / "model-one.json"
    evaluation_one = root / "evaluation-one.json"
    release_one = root / "release-one.json"
    model_two = root / "model-two.json"
    evaluation_two = root / "evaluation-two.json"
    release_two = root / "release-two.json"
    train_model(training, model_one, ridge=1.0)
    evaluate_model(model_one, heldout, evaluation_one)
    from ecc_experience.modeling.model import publish_model

    publish_model(model_one, evaluation_one, release_one)
    train_model(training, model_two, ridge=2.0)
    evaluate_model(model_two, heldout, evaluation_two)
    publish_model(model_two, evaluation_two, release_two)
    registry = root / "registry"
    assert promote(release_one, registry)["status"] == "promoted"
    assert promote(release_two, registry)["status"] == "promoted"
    assert status(registry)["active_release_id"] == read_model_release(release_two)["release_id"]
    rolled_back = rollback(registry)
    assert rolled_back["release_id"] == read_model_release(release_one)["release_id"]
    assert status(registry)["active_release_id"] == rolled_back["release_id"]


def test_model_evaluation_rejects_runtime_scope_change(modeling_files):
    training, heldout, root = modeling_files
    model_path = root / "model.json"
    train_model(training, model_path)
    payload = json.loads(heldout.read_text())
    payload["rows"][0]["runtime"] = {"ecc": "different-runtime"}
    identity = {
        key: payload[key]
        for key in (
            "schema",
            "feature_schema",
            "release_id",
            "release_sha256",
            "target",
            "through_step",
            "groups",
            "rows",
        )
    }
    payload["dataset_id"] = f"dataset-{digest(identity)}"
    heldout.write_bytes(canonical_bytes(payload))
    with pytest.raises(ExperienceError, match="runtime") as error:
        evaluate_model(model_path, heldout)
    assert error.value.code == "experience_model_incompatible"


def test_model_release_tampering_is_rejected(modeling_files):
    training, heldout, root = modeling_files
    model_path = root / "model.json"
    evaluation_path = root / "evaluation.json"
    release_path = root / "release.json"
    train_model(training, model_path)
    evaluate_model(model_path, heldout, evaluation_path)
    from ecc_experience.modeling.model import publish_model

    publish_model(model_path, evaluation_path, release_path)
    payload = json.loads(release_path.read_text())
    payload["scope"] = "tampered"
    release_path.write_bytes(canonical_bytes(payload))
    with pytest.raises(ExperienceError, match="identity"):
        read_model_release(release_path)


def test_model_cli_train_and_evaluate(modeling_files):
    training, heldout, root = modeling_files
    model_path = root / "cli-model.json"
    evaluation_path = root / "cli-evaluation.json"
    runner = CliRunner()
    trained = runner.invoke(
        app,
        [
            "experience",
            "model",
            "train",
            "--dataset",
            str(training),
            "--output",
            str(model_path),
            "--json",
        ],
    )
    assert trained.exit_code == 0, trained.output
    evaluated = runner.invoke(
        app,
        [
            "experience",
            "model",
            "evaluate",
            "--model",
            str(model_path),
            "--dataset",
            str(heldout),
            "--output",
            str(evaluation_path),
            "--json",
        ],
    )
    assert evaluated.exit_code == 0, evaluated.output
    assert json.loads(evaluated.stdout)[0]["status"] == "pass"


def test_dataset_build_reads_verified_release(workspace_factory, tmp_path):
    workspace = workspace_factory("dataset-case")
    source = workspace / "input.v"
    source.write_text("module sample; endmodule\n")
    snapshot_path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["workspaceSpec"] = {
        "design": {"topModule": "sample"},
        "pdk": {"familyId": "ics55"},
        "flow": {"flowId": "test"},
        "parameters": {"floorplan.core_util": 0.4},
        "inputs": [{"inputId": "rtl", "role": "rtl"}],
    }
    snapshot["workspaceBindings"] = {"inputs": {"rtl": str(source)}}
    snapshot["flow"]["steps"][0].update(state="Success", checklist_status={"status": "passed"})
    snapshot["flow"]["steps"].append({"name": "Place", "tool": "openroad", "state": "Success"})
    snapshot["qorSnapshotExtension"].update(
        status="available",
        score=88.0,
        feasibility={"status": "PASS", "gates": []},
    )
    snapshot["qorSnapshotExtension"].pop("reason", None)
    snapshot["artifacts"][0]["kind"] = "qor_metrics"
    snapshot_path.write_text(json.dumps(snapshot))
    (workspace / "home/flow.json").write_text(json.dumps(snapshot["flow"]))
    context = {
        "schema": "ecc-experience-execution-context/1",
        "attempt_id": "dataset-case",
        "process": {"status": "available", "fingerprint": "ics55-process"},
        "runtime": {"ecc": "test", "tools": {"yosys": "2026"}},
    }
    repository = ExperienceStore(tmp_path / "store")
    case = collect_committed_case(
        workspace,
        repository,
        read_workspace_observation,
        attempt_id="dataset-case",
        execution_context=context,
    ).case
    release_path = tmp_path / "release.json"
    create_release([case.case_id], repository.root, release_path)
    output = tmp_path / "dataset.json"
    result = build_dataset(
        release_path,
        repository.root,
        output,
        target="final_qor",
        through_step="Synthesis",
    )
    assert result["summary"]["row_count"] == 1
    payload = json.loads(output.read_text())
    assert payload["schema"] == "ecc-experience-model-dataset/2"
    assert payload["feature_schema"] == "ecc-experience-model-features/2"
    assert payload["rows"][0]["target"] == 88.0
    assert payload["rows"][0]["process_fingerprint"] == "ics55-process"
    assert payload["rows"][0]["feature_coverage"] == {
        "stage": "Synthesis",
        "identity_fields": 3,
        "required_identity_fields": 4,
    }
    assert "constraints.clock_period_count" in payload["rows"][0]["features"]
