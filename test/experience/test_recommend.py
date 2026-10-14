import json

from ecc_experience.api import collect, recommend


def test_recommend_returns_same_input_configuration_as_observed_only(
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
    store = tmp_path / "store"
    case = collect(workspace, store).case

    result = recommend(workspace, store)

    assert result["status"] == "recommendations_available"
    assert result["candidates"][0]["case_id"] == case.case_id
    recommendation = result["recommendations"][0]
    assert recommendation["safe_to_apply"] is False
    assert recommendation["confidence"] == "observed_only"
    assert recommendation["parameters"] == {"place.density": 0.7}


def test_recommend_does_not_guess_without_input_fingerprint(workspace_factory, tmp_path):
    workspace = workspace_factory()

    result = recommend(workspace, tmp_path / "store")

    assert result["status"] == "insufficient_evidence"
    assert result["recommendations"] == []
