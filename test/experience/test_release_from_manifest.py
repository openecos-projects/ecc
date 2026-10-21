import json
import shutil

import pytest

from ecc_experience.files import case_identity, file_digest
from ecc_experience.knowledge.normalize import normalize_stores
from ecc_experience.knowledge.release import verify_release
from ecc_experience.knowledge.release_from_manifest import release_from_manifest
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import Evidence, ExperienceError
from test.experience.test_summary import _case


def _put(store, case, copies=None):
    case = case.model_copy(update={"case_id": case_identity(case.model_dump())})
    store.put(case, copies or {})
    return case


def test_promotes_positive_cases_to_independent_release_store(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = ExperienceStore(tmp_path / "source")
    case = _put(source, _case(workspace, "promote"))
    normalized = normalize_stores([source.root], tmp_path / "normalized")
    destination = tmp_path / "release-store"
    release_path = tmp_path / "release.json"

    result = release_from_manifest(
        normalized["output"] + "/normalized-manifest.json", destination, release_path
    )

    assert result["status"] == "created"
    assert result["selection_status"] == "complete"
    assert result["included_count"] == 1
    assert result["excluded"] == []
    assert verify_release(release_path, destination)["status"] == "pass"
    assert ExperienceStore(destination).read(case.case_id).case_id == case.case_id


def test_copies_evidence_and_excludes_case_changed_after_normalization(tmp_path):
    good_workspace = tmp_path / "good-workspace"
    bad_workspace = tmp_path / "bad-workspace"
    good_workspace.mkdir()
    bad_workspace.mkdir()
    source = ExperienceStore(tmp_path / "source")
    evidence = good_workspace / "report.json"
    evidence.write_text('{"status": "pass"}')
    checksum, size = file_digest(evidence)
    good = _case(good_workspace, "good").model_copy(
        update={
            "evidence": [
                Evidence(
                    reference="report.json",
                    status="available",
                    sha256=checksum,
                    bytes=size,
                    stored_path="evidence/report.json",
                )
            ]
        }
    )
    good = _put(source, good, {"evidence/report.json": evidence.read_bytes()})
    bad = _put(source, _case(bad_workspace, "bad"))
    normalize_stores([source.root], tmp_path / "normalized")
    shutil.rmtree(bad_workspace)

    result = release_from_manifest(
        tmp_path / "normalized/normalized-manifest.json",
        tmp_path / "release-store",
        tmp_path / "release.json",
    )

    assert result["status"] == "created"
    assert result["exit_code"] == 7
    assert result["included_count"] == 1
    assert result["excluded"] == [
        {
            "case_id": bad.case_id,
            "store": str(source.root),
            "status": "excluded",
            "reason": "Current verification is unknown/pass",
        }
    ]
    assert (
        ExperienceStore(tmp_path / "release-store").case_directory(good.case_id)
        / "evidence/report.json"
    ).read_bytes() == evidence.read_bytes()


def test_rejects_tampered_manifest_and_shared_destination(tmp_path):
    source = ExperienceStore(tmp_path / "source")
    _put(source, _case(tmp_path, "invalid"))
    normalize_stores([source.root], tmp_path / "normalized")
    manifest_path = tmp_path / "normalized/normalized-manifest.json"
    payload = json.loads(manifest_path.read_text())
    payload["selections"]["positive"] = []
    manifest_path.write_text(json.dumps(payload))

    with pytest.raises(ExperienceError, match="identity mismatch"):
        release_from_manifest(manifest_path, tmp_path / "destination", tmp_path / "release.json")
    valid = normalize_stores([source.root], tmp_path / "normalized-good")
    with pytest.raises(ExperienceError, match="independent store"):
        release_from_manifest(
            valid["output"] + "/normalized-manifest.json",
            source.root,
            tmp_path / "release.json",
        )
