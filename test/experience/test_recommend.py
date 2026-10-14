import json

from chipcompiler.engine.snapshot import _artifact_id
from chipcompiler.engine.snapshot_qor import unavailable_qor_snapshot_extension
from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.api import collect, recommend, release_create
from ecc_experience.collection.collect import collect_committed_case
from ecc_experience.knowledge.store import ExperienceStore


def _prepare_verified_workspace(root, input_file, parameter):
    snapshot_path = root / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["workspaceSpec"] = {
        "design": {"topModule": "sample"},
        "inputs": [{"inputId": "rtl", "role": "rtl"}],
        "parameters": {"place.density": parameter},
    }
    snapshot["workspaceBindings"] = {"inputs": {"rtl": str(input_file)}}
    qor = unavailable_qor_snapshot_extension("test fixture")
    qor["status"] = "available"
    qor.pop("reason")
    qor["score"] = 90.0 + parameter
    qor["scalarStatus"] = "GREEN"
    snapshot["qorSnapshotExtension"] = qor
    (root / "home/params.toml").write_text("[params]\n")
    workspace_id = snapshot["workspaceId"]
    for reference in ("home/checklist.json", "home/params.toml"):
        snapshot["artifacts"].append(
            {
                "artifactId": _artifact_id(workspace_id, reference),
                "reference": reference,
                "availability": "available",
            }
        )
    snapshot_path.write_text(json.dumps(snapshot))


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
        "parameters": {
            "place.density": 0.7,
            "sta.liberty": [{"path": "/private/pdk/lib.lib"}],
        },
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
    assert recommendation["parameters"] == {
        "place.density": 0.7,
        "sta.liberty": [{"path": "<path-redacted>"}],
    }


def test_recommend_does_not_guess_without_input_fingerprint(workspace_factory, tmp_path):
    workspace = workspace_factory()

    result = recommend(workspace, tmp_path / "store")

    assert result["status"] == "insufficient_evidence"
    assert result["recommendations"] == []


def test_recommend_uses_only_cases_from_verified_release(workspace_factory, tmp_path):
    input_file = tmp_path / "design.v"
    input_file.write_text("module sample; endmodule")
    first_workspace = workspace_factory("first")
    second_workspace = workspace_factory("second")
    _prepare_verified_workspace(first_workspace, input_file, 0.7)
    _prepare_verified_workspace(second_workspace, input_file, 0.8)
    store = tmp_path / "store"
    first = collect_committed_case(
        first_workspace,
        ExperienceStore(store),
        read_workspace_observation,
        attempt_id="attempt-first",
    ).case
    second = collect_committed_case(
        second_workspace,
        ExperienceStore(store),
        read_workspace_observation,
        attempt_id="attempt-second",
    ).case
    release = tmp_path / "release.json"
    release_create([first.case_id], store, release)

    result = recommend(second_workspace, store, release=release)

    assert result["status"] == "recommendations_available"
    assert result["release_verification"]["status"] == "pass"
    assert [item["case_id"] for item in result["candidates"]] == [first.case_id]
    assert result["recommendations"][0]["case_id"] == first.case_id
    assert second.case_id not in result["recommendations"]
