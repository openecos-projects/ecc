import json

from chipcompiler.engine.snapshot_qor import unavailable_qor_snapshot_extension
from ecc_experience.api import collect, evaluate


def _prepare_workspace(root, input_file, score):
    snapshot_path = root / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["workspaceSpec"] = {
        "design": {"topModule": "sample"},
        "inputs": [{"inputId": "rtl", "role": "rtl"}],
    }
    snapshot["workspaceBindings"] = {"inputs": {"rtl": str(input_file)}}
    qor = unavailable_qor_snapshot_extension("test fixture")
    qor["status"] = "available"
    qor.pop("reason")
    qor["score"] = score
    qor["scalarStatus"] = "GREEN"
    snapshot["qorSnapshotExtension"] = qor
    snapshot_path.write_text(json.dumps(snapshot))


def test_evaluate_compares_verified_cases(workspace_factory, tmp_path):
    input_file = tmp_path / "design.v"
    input_file.write_text("module sample; endmodule")
    baseline_workspace = workspace_factory("baseline")
    candidate_workspace = workspace_factory("candidate")
    _prepare_workspace(baseline_workspace, input_file, 90.0)
    _prepare_workspace(candidate_workspace, input_file, 100.0)
    store = tmp_path / "store"
    baseline = collect(baseline_workspace, store).case
    candidate = collect(candidate_workspace, store).case

    result = evaluate(baseline.case_id, candidate.case_id, store)

    assert result["status"] == "complete"
    assert result["comparison"] == "improved"
    assert result["score_delta"] == 10.0
    assert result["score_delta_percent"] == 100 / 9


def test_evaluate_rejects_different_inputs(workspace_factory, tmp_path):
    first_input = tmp_path / "first.v"
    second_input = tmp_path / "second.v"
    first_input.write_text("module first; endmodule")
    second_input.write_text("module second; endmodule")
    first = workspace_factory("first")
    second = workspace_factory("second")
    _prepare_workspace(first, first_input, 90.0)
    _prepare_workspace(second, second_input, 100.0)
    store = tmp_path / "store"
    baseline = collect(first, store).case
    candidate = collect(second, store).case

    result = evaluate(baseline.case_id, candidate.case_id, store)

    assert result["status"] == "incompatible"
    assert result["comparison"] == "unavailable"
