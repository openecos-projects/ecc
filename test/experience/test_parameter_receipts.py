import hashlib
import json
from pathlib import Path

from ecc_experience.api import collect


def canonical_sha(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def file_sha(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_receipt(workspace: Path, *, status="effective", corrupt_hash=False):
    candidate = workspace / ".agent/candidates/candidate-1"
    analysis = candidate / "analysis"
    analysis.mkdir(parents=True)
    config = candidate / "config/dreamplace.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"target_density": 0.4}, separators=(",", ":")))
    after = analysis / "snapshots/after.json"
    after.parent.mkdir()
    after.write_text(json.dumps({"target_density": 0.4}, separators=(",", ":")))
    config_sha = file_sha(config)
    after_sha = file_sha(after)
    patch = [{"knob_id": "target_density", "value": 0.4}]
    materialization = {
        "schema": "ecc.workspace.candidate_materialization.v1",
        "schema_version": 1,
        "candidate_id": "candidate-1",
        "target_step": "place",
        "patch": patch,
        "patch_sha256": canonical_sha(patch),
        "receipt_ref": "analysis/candidate_materialization.v1.json",
    }
    materialization["receipt_sha256"] = canonical_sha(materialization)
    (analysis / "candidate_materialization.v1.json").write_text(json.dumps(materialization))
    receipt = {
        "schema_version": "tool.parameter_application_receipt.v2",
        "receipt_id": "receipt-1",
        "context": {"run_id": "attempt-1", "stage": "place"},
        "requested": {"knob_id": "target_density", "value": 0.4, "unit": "ratio"},
        "materialization": {
            "candidate_id": "candidate-1",
            "target_step": "place",
            "receipt_ref": "analysis/candidate_materialization.v1.json",
            "receipt_sha256": materialization["receipt_sha256"],
            "patch_sha256": materialization["patch_sha256"],
            "written_value": 0.4,
            "unit": "ratio",
            "config_ref": "config/dreamplace.json",
            "config_after_sha256": config_sha,
            "after_snapshot_ref": "analysis/snapshots/after.json",
            "after_snapshot_sha256": after_sha,
        },
        "status": status,
        "actual_value": 0.4 if status == "effective" else None,
        "reason": "test",
    }
    receipt["evidence_sha256"] = canonical_sha(receipt)
    if corrupt_hash:
        receipt["status"] = "unknown"
    (analysis / "parameter_application_receipt.v2.json").write_text(json.dumps(receipt))


def prepare_workspace(workspace):
    path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(path.read_text())
    snapshot["workspaceSpec"] = {
        "design": {"topModule": "top"},
        "parameters": {"place.target_density": 0.4},
    }
    snapshot["flow"]["steps"].append({"name": "place", "tool": "dreamplace", "state": "Success"})
    path.write_text(json.dumps(snapshot))
    (workspace / "home/flow.json").write_text(json.dumps(snapshot["flow"]))


def test_effective_receipt_is_bound_to_configuration_and_workspace(workspace_factory, tmp_path):
    workspace = workspace_factory("receipt-valid")
    prepare_workspace(workspace)
    prepare_receipt(workspace)

    case = collect(workspace, tmp_path / "store").case

    assert case.parameter_evidence.level == "applied"
    assert case.parameter_evidence.receipt_status == "valid"
    assert case.parameter_evidence.receipt_sha256
    assert case.parameter_evidence.applied_parameters[0].knob_id == "target_density"
    assert any(
        item.reference.endswith("parameter_application_receipt.v2.json") for item in case.evidence
    )


def test_missing_receipt_never_upgrades_configured_parameters(workspace_factory, tmp_path):
    workspace = workspace_factory("receipt-missing")
    prepare_workspace(workspace)

    case = collect(workspace, tmp_path / "store").case

    assert case.parameter_evidence.level == "configured"
    assert case.parameter_evidence.receipt_status == "missing"
    assert case.parameter_evidence.applied_parameters == []


def test_inactive_receipt_is_valid_but_not_applied(workspace_factory, tmp_path):
    workspace = workspace_factory("receipt-inactive")
    prepare_workspace(workspace)
    prepare_receipt(workspace, status="inactive")

    case = collect(workspace, tmp_path / "store").case

    assert case.parameter_evidence.level == "configured"
    assert case.parameter_evidence.receipt_status == "valid"
    assert case.parameter_evidence.applied_parameters == []
    assert any("inactive" in item for item in case.parameter_evidence.limitations)


def test_corrupt_receipt_is_unknown_and_explained(workspace_factory, tmp_path):
    workspace = workspace_factory("receipt-corrupt")
    prepare_workspace(workspace)
    prepare_receipt(workspace, corrupt_hash=True)

    case = collect(workspace, tmp_path / "store").case

    assert case.parameter_evidence.level == "unknown"
    assert case.parameter_evidence.receipt_status == "invalid"
    assert any("receipt" in item for item in case.parameter_evidence.limitations)
