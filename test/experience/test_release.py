import json

import pytest

from chipcompiler.engine.snapshot import _artifact_id
from chipcompiler.engine.snapshot_qor import unavailable_qor_snapshot_extension
from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.collection.collect import collect_committed_case
from ecc_experience.knowledge.release import create_release, verify_release
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import ExperienceError


def _prepare_workspace(root, input_file):
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
    qor["score"] = 95.0
    qor["scalarStatus"] = "GREEN"
    snapshot["qorSnapshotExtension"] = qor
    (root / "home/params.toml").write_text("[params]\n")
    snapshot["artifacts"].append(
        {
            "artifactId": _artifact_id("identity-workspace", "home/checklist.json"),
            "reference": "home/checklist.json",
            "availability": "available",
        }
    )
    snapshot["artifacts"].append(
        {
            "artifactId": _artifact_id("identity-workspace", "home/params.toml"),
            "reference": "home/params.toml",
            "availability": "available",
        }
    )
    snapshot_path.write_text(json.dumps(snapshot))


def test_release_create_and_verify(workspace_factory, tmp_path):
    input_file = tmp_path / "design.v"
    input_file.write_text("module sample; endmodule")
    workspace = workspace_factory()
    _prepare_workspace(workspace, input_file)
    store = tmp_path / "store"
    case = collect_committed_case(
        workspace,
        ExperienceStore(store),
        read_workspace_observation,
        attempt_id="attempt-test-release",
    ).case
    release_path = tmp_path / "release.json"

    created = create_release([case.case_id], store, release_path)
    verified = verify_release(release_path, store)

    assert created["status"] == "created"
    assert verified["status"] == "pass"
    assert verified["cases"][0]["release_record_matches"] is True
    assert create_release([case.case_id], store, release_path)["status"] == "already_present"


def test_release_rejects_unverified_case(tmp_path, workspace_factory):
    store = tmp_path / "store"
    case = collect_committed_case(
        workspace_factory(),
        ExperienceStore(store),
        read_workspace_observation,
        attempt_id="attempt-test-release",
    ).case

    with pytest.raises(ExperienceError, match="not verified"):
        create_release([case.case_id], store, tmp_path / "release.json")
