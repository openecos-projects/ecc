import json
from typing import Any

import pytest

from ecc_experience.files import case_identity, file_digest
from ecc_experience.knowledge.normalize import normalize_stores
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import Evidence, ExperienceError
from test.experience.test_summary import _case


def _put(store, case):
    case = case.model_copy(update={"case_id": case_identity(case.model_dump())})
    store.put(case, {})
    return case


def test_merge_preserves_sources_and_repeated_configurations(tmp_path):
    first = ExperienceStore(tmp_path / "first")
    second = ExperienceStore(tmp_path / "second")
    case = _put(first, _case(tmp_path, "first"))
    second.put(case, {})
    repeated = _put(second, _case(tmp_path, "repeated"))
    before = {path: path.read_bytes() for path in tmp_path.glob("*/cases/*/case.json")}

    result = normalize_stores([second.root, first.root, first.root], tmp_path / "normalized")

    assert result["status"] == "pass"
    assert result["counts"] == {
        "stores": 2,
        "source_observations": 3,
        "unique_cases": 2,
        "exact_duplicate_observations": 1,
        "configuration_groups": 1,
        "quality": {
            "verified_pass": 2,
            "verified_observation": 0,
            "blocked": 0,
            "qor_unknown": 0,
            "incomplete": 0,
            "evidence_invalid": 0,
        },
        "positive": 2,
        "negative": 0,
        "quarantined_sources": 0,
        "read_errors": 0,
    }
    merged = next(row for row in result["cases"] if row["case_id"] == case.case_id)
    assert [source["store"] for source in merged["provenance"]] == [
        str(first.root),
        str(second.root),
    ]
    assert result["configuration_groups"][0]["case_ids"] == sorted([case.case_id, repeated.case_id])
    assert before == {path: path.read_bytes() for path in before}
    persisted = json.loads((tmp_path / "normalized/normalized-manifest.json").read_text())
    assert persisted == {key: value for key, value in result.items() if key != "output"}
    assert (tmp_path / "normalized/normalized-manifest.md").is_file()
    rerun = normalize_stores([first.root, second.root], tmp_path / "rerun")
    assert rerun["manifest_id"] == result["manifest_id"]


@pytest.mark.parametrize("change", ["tool", "parameters", "process", "input", "flow", "missing"])
def test_configuration_identity_does_not_mix_incompatible_or_unknown_cases(tmp_path, change):
    store = ExperienceStore(tmp_path / "store")
    _put(store, _case(tmp_path, "baseline"))
    candidate = _case(tmp_path, "candidate")
    facts: Any = candidate.facts
    if change == "tool":
        facts["experienceExecutionContext"]["runtime"]["tools"]["yosys"] = "0.61"
    elif change == "parameters":
        facts["workspaceSpec"]["parameters"]["place.target_density"] = 0.5
    elif change == "flow":
        facts["flow"]["steps"][0]["name"] = "other_step"
    elif change == "missing":
        facts.pop("experienceExecutionContext")
    else:
        field = "process_fingerprint" if change == "process" else "input_content_fingerprint"
        candidate = candidate.model_copy(update={field: "different"})
    _put(store, candidate)

    result = normalize_stores([store.root], tmp_path / "out")

    assert result["counts"]["configuration_groups"] == 2
    if change == "missing":
        group = next(
            group for group in result["configuration_groups"] if not group["identity_complete"]
        )
        assert group["missing_identity"] == ["runtime"]


def test_negative_missing_qor_and_legacy_are_separated(tmp_path):
    store = ExperienceStore(tmp_path / "store")
    negative = _put(store, _case(tmp_path, "negative", signoff="blocked", qor=False))
    missing = _put(store, _case(tmp_path, "missing", qor=False))
    legacy = _case(tmp_path, "legacy", signoff="blocked")
    legacy = _put(store, legacy.model_copy(update={"validation_scope": "legacy_import"}))

    result = normalize_stores([store.root], tmp_path / "out")

    assert result["exit_code"] == 7
    selections = result["selections"]
    assert [row["case_id"] for row in selections["negative"]] == [negative.case_id]
    assert [row["case_id"] for row in selections["qor_missing"]] == [missing.case_id]
    assert [row["case_id"] for row in selections["other"]] == [legacy.case_id]
    assert selections["positive"] == selections["quarantine"] == []


@pytest.mark.parametrize("damage", ["copied_evidence", "source_changed", "case_json"])
def test_invalid_sources_are_quarantined_without_losing_a_valid_copy(tmp_path, damage):
    first = ExperienceStore(tmp_path / "first")
    second = ExperienceStore(tmp_path / "second")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evidence_path = workspace / "report.json"
    evidence_path.write_text("{}")
    checksum, size = file_digest(evidence_path)
    case = _case(workspace, "evidence")
    evidence = Evidence(
        reference="report.json",
        status="available",
        sha256=checksum,
        bytes=size,
        stored_path="evidence/report.json",
    )
    case = case.model_copy(update={"evidence": [evidence]})
    case = case.model_copy(update={"case_id": case_identity(case.model_dump())})
    for store in (first, second):
        store.put(case, {"evidence/report.json": b"{}"})
    if damage == "copied_evidence":
        (first.case_directory(case.case_id) / "evidence/report.json").write_text("changed")
    elif damage == "source_changed":
        moved = tmp_path / "different-source"
        moved.mkdir()
        (moved / "report.json").write_text("changed")
        payload = case.model_dump()
        payload["source"]["workspace_root"] = str(moved)
        (first.case_directory(case.case_id) / "case.json").write_text(json.dumps(payload))
    else:
        (first.case_directory(case.case_id) / "case.json").write_text("invalid")

    result = normalize_stores([first.root, second.root], tmp_path / "out")

    assert result["exit_code"] == 6
    assert result["counts"]["positive"] == 1
    assert result["counts"]["quarantined_sources"] == 1
    assert result["selections"]["positive"][0]["store"] == str(second.root)
    quarantine = result["selections"]["quarantine"][0]
    assert quarantine["store"] == str(first.root)
    if damage == "source_changed":
        assert quarantine["integrity"] == "pass"
        assert quarantine["verification"] == "fail"


def test_active_writer_makes_observations_ineligible_without_changing_store(tmp_path):
    store = ExperienceStore(tmp_path / "store")
    _put(store, _case(tmp_path, "active"))
    lock = store.root / ".write-lock"
    lock.mkdir()

    result = normalize_stores([store.root], tmp_path / "out")

    assert result["exit_code"] == 7
    assert result["counts"]["positive"] == 0
    assert result["stores"][0]["changed_during_read"]
    assert lock.is_dir()


def test_store_changes_during_scan_are_reported(tmp_path, monkeypatch):
    store = ExperienceStore(tmp_path / "store")
    _put(store, _case(tmp_path, "first"))
    real_read = ExperienceStore.read
    changed = False

    def read(repository, case_id):
        nonlocal changed
        case = real_read(repository, case_id)
        if not changed:
            changed = True
            _put(store, _case(tmp_path, "added"))
        return case

    monkeypatch.setattr(ExperienceStore, "read", read)
    result = normalize_stores([store.root], tmp_path / "out")

    assert result["exit_code"] == 7
    assert result["counts"]["positive"] == 0
    assert result["stores"][0]["changed_during_read"]


def test_missing_and_empty_stores_are_not_success(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert normalize_stores([empty], tmp_path / "empty-out")["exit_code"] == 7
    result = normalize_stores([tmp_path / "missing"], tmp_path / "missing-out")
    assert result["exit_code"] == 6
    assert result["counts"]["read_errors"] == 1


def test_output_is_exclusive_and_must_be_outside_source_stores(tmp_path):
    store = ExperienceStore(tmp_path / "store")
    store.root.mkdir()
    with pytest.raises(ExperienceError, match="outside"):
        normalize_stores([store.root], store.root / "normalized")
    assert not (store.root / "normalized").exists()
    alias = tmp_path / "alias"
    alias.symlink_to(store.root, target_is_directory=True)
    with pytest.raises(ExperienceError, match="outside"):
        normalize_stores([store.root], alias / "normalized")
    normalize_stores([store.root], tmp_path / "out")
    before = (tmp_path / "out/normalized-manifest.json").read_bytes()
    with pytest.raises(ExperienceError, match="exists"):
        normalize_stores([store.root], tmp_path / "out")
    assert before == (tmp_path / "out/normalized-manifest.json").read_bytes()
    with pytest.raises(ExperienceError, match="At least one"):
        normalize_stores([], tmp_path / "unused")
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "not-created", target_is_directory=True)
    with pytest.raises(ExperienceError, match="exists"):
        normalize_stores([store.root], dangling)
    assert not (tmp_path / "not-created").exists()
