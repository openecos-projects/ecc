import json

from ecc_experience.api import plan


def test_plan_writes_manual_review_policy_without_modifying_workspace(
    workspace_factory, tmp_path
):
    workspace = workspace_factory()
    input_file = tmp_path / "design.v"
    input_file.write_text("module sample; endmodule")
    snapshot_path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["workspaceSpec"] = {
        "design": {"topModule": "sample"},
        "inputs": [{"inputId": "rtl", "role": "rtl"}],
        "parameters": {"place.density": 0.7},
    }
    snapshot["workspaceBindings"] = {"inputs": {"rtl": str(input_file)}}
    snapshot_path.write_text(json.dumps(snapshot))
    before = snapshot_path.read_bytes()
    store = tmp_path / "store"

    from ecc_experience.api import collect

    collect(workspace, store)
    output = tmp_path / "plan.json"
    result = plan(workspace, store, output)

    payload = json.loads(output.read_text())
    assert result["status"] == "recommendations_available"
    assert payload["kind"] == "ecc-experience-optimization-plan"
    assert payload["execution_policy"]["auto_apply"] is False
    assert payload["execution_policy"]["requires_new_workspace"] is True
    assert payload["candidates"][0]["safe_to_apply"] is False
    assert snapshot_path.read_bytes() == before


def test_plan_records_insufficient_evidence(tmp_path, workspace_factory):
    output = tmp_path / "plan.json"

    result = plan(workspace_factory(), tmp_path / "missing-store", output)

    assert result["status"] == "insufficient_evidence"
    assert result["candidates"] == []
    assert json.loads(output.read_text())["reason"] == (
        "Query workspace has no complete input content fingerprint"
    )
