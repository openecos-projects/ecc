import hashlib
import json

from ecc_experience.api import dse_plan, dse_run
from ecc_experience.files import canonical_bytes, digest
from ecc_experience.modeling.model import evaluate_model, publish_model, train_model
from test.experience import test_dse as fixtures
from test.experience.test_modeling import row

dse_project = fixtures.dse_project
version2_spec = fixtures.version2_spec
simulated_cli = fixtures.simulated_cli


def _write_dataset(path, rows, through_step):
    identity = {
        "schema": "ecc-experience-model-dataset/1",
        "feature_schema": "ecc-experience-model-features/1",
        "release_id": "release-model-v2",
        "release_sha256": "sha-model-v2",
        "target": "final_qor",
        "through_step": through_step,
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


def _bind_process(tmp_path, workspace):
    files = {}
    declarations = []
    for role in ("tech", "lef", "liberty"):
        path = tmp_path / f"{role}.pdk"
        path.write_text(role)
        files[role] = str(path)
        declarations.append({"role": role, "fileId": role})
    snapshot_path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["workspaceSpec"]["pdk"] = {
        "familyId": "ics55",
        "mode": "manual",
        "files": declarations,
    }
    snapshot["workspaceBindings"] = {
        **snapshot.get("workspaceBindings", {}),
        "pdk": {"files": files},
    }
    snapshot_path.write_text(json.dumps(snapshot))


def test_v2_model_pre_screen_records_predictions_without_bypassing_measured_flow(
    dse_project, simulated_cli, version2_spec, tmp_path
):
    workspace, store, path = dse_project
    _bind_process(tmp_path, workspace)
    frozen = dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    process_fingerprint = frozen["process"]["fingerprint"]
    runtime = frozen["runtime"]

    training_rows = []
    for index in range(6):
        item = row(index, index + 1, f"family-{index % 2}")
        item.update(
            process_fingerprint=process_fingerprint,
            runtime=runtime,
        )
        training_rows.append(item)
    heldout_rows = []
    for index in range(4):
        item = row(index + 10, index + 1.5, f"family-{index % 2}")
        item.update(process_fingerprint=process_fingerprint, runtime=runtime)
        heldout_rows.append(item)
    training = tmp_path / "training.json"
    heldout = tmp_path / "heldout.json"
    _write_dataset(training, training_rows, "postFloorplan")
    _write_dataset(heldout, heldout_rows, "postFloorplan")
    model = tmp_path / "model.json"
    evaluation = tmp_path / "evaluation.json"
    release = tmp_path / "model-release.json"
    train_model(training, model)
    evaluate_model(model, heldout, evaluation)
    publish_model(model, evaluation, release)

    result = dse_run(path, path.parent / "output", model_release=release)

    assert result["status"] == "complete", result
    assert result["model"]["status"] == "available"
    assert result["model"]["policy"] == "measured_objective_tie_break_only"
    assert all(
        item["model_prediction"]["status"] == "available"
        for item in result["trials"]
        if item["status"] == "stage_passed"
    )
    assert all(
        item["model_prediction"]["prediction"]["interval"]["basis"]
        == "held_out_grouped_calibration"
        for item in result["trials"]
        if item["status"] == "stage_passed"
    )
    assert result["full_validation"]["status"] == result["fresh_validation"]["status"] == "passed"


def test_multirung_model_clears_an_early_rung_scope_rejection(
    dse_project, simulated_cli, version2_spec, tmp_path
):
    workspace, store, path = dse_project
    _bind_process(tmp_path, workspace)
    snapshot_path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["flow"]["steps"].insert(
        2,
        {
            "name": "place",
            "tool": "dreamplace",
            "state": "Success",
            "checklist_status": {"status": "passed", "blocked": False},
        },
    )
    reference = "place_dreamplace/analysis/qor_metrics.json"
    report_path = workspace / reference
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "step": "place",
                "tool": "dreamplace",
                "status": "success",
                "integrity": {"status": "pass"},
                "metrics": [{"id": "core_area", "value": 100.0, "unit": "um^2"}],
            }
        )
    )
    snapshot["artifacts"].append(
        {
            "artifactId": "artifact-"
            + hashlib.sha256(f"{snapshot['workspaceId']}\0{reference}".encode()).hexdigest()[:32],
            "reference": reference,
            "kind": "qor_metrics",
            "stepId": "place",
            "availability": "available",
        }
    )
    snapshot_path.write_text(json.dumps(snapshot))
    (workspace / "home/flow.json").write_text(json.dumps(snapshot["flow"]))
    settings = json.loads(version2_spec.read_text())
    settings["rungs"] = [
        {"through_step": "postFloorplan", "promote_count": 1},
        {"through_step": "place", "promote_count": 1},
    ]
    settings["limits"]["max_trials"] = 7
    version2_spec.write_text(json.dumps(settings))
    frozen = dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)

    process_fingerprint = frozen["process"]["fingerprint"]
    runtime = frozen["runtime"]
    training_rows = []
    for index in range(6):
        item = row(index, index + 1, f"family-{index % 2}")
        item.update(process_fingerprint=process_fingerprint, runtime=runtime)
        training_rows.append(item)
    heldout_rows = []
    for index in range(4):
        item = row(index + 10, index + 1.5, f"family-{index % 2}")
        item.update(process_fingerprint=process_fingerprint, runtime=runtime)
        heldout_rows.append(item)
    training = tmp_path / "training.json"
    heldout = tmp_path / "heldout.json"
    _write_dataset(training, training_rows, "place")
    _write_dataset(heldout, heldout_rows, "place")
    model = tmp_path / "model.json"
    evaluation = tmp_path / "evaluation.json"
    release = tmp_path / "model-release.json"
    train_model(training, model)
    evaluate_model(model, heldout, evaluation)
    publish_model(model, evaluation, release)

    result = dse_run(path, path.parent / "output", model_release=release)

    assert result["status"] == "complete", result
    assert result["model"]["status"] == "available"
    assert result["model"].get("reason") is None
    assert any(
        item["rung"] == 0
        and item["model_prediction"]["status"] == "unknown"
        and "outside the model stage" in item["model_prediction"]["reason"]
        for item in result["trials"]
        if item["status"] == "stage_passed"
    )
    assert any(
        item["rung"] == 1 and item["model_prediction"]["status"] == "available"
        for item in result["trials"]
        if item["status"] == "stage_passed"
    )


def test_incompatible_model_release_falls_back_to_measured_objective(
    dse_project, simulated_cli, version2_spec, tmp_path
):
    workspace, store, path = dse_project
    dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    rows = [row(index, index + 1, f"family-{index % 2}") for index in range(6)]
    training = tmp_path / "training.json"
    heldout = tmp_path / "heldout.json"
    _write_dataset(training, rows, "Synthesis")
    _write_dataset(
        heldout,
        [row(index + 10, index + 1.5, f"family-{index % 2}") for index in range(4)],
        "Synthesis",
    )
    model = tmp_path / "model.json"
    evaluation = tmp_path / "evaluation.json"
    release = tmp_path / "model-release.json"
    train_model(training, model)
    evaluate_model(model, heldout, evaluation)
    publish_model(model, evaluation, release)

    result = dse_run(path, path.parent / "output", model_release=release)

    assert result["status"] == "complete", result
    assert result["model"]["status"] == "unknown"
    assert all(
        item["model_prediction"]
        == {
            "status": "unknown",
            "reason": item["model_prediction"]["reason"],
            "fallback": "measured_objective",
        }
        for item in result["trials"]
        if item["status"] == "stage_passed"
    )
