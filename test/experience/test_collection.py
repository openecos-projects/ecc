import json
import shutil

import pytest

from ecc_experience.api import collect, list_cases, show, verify
from ecc_experience.files import file_digest, safe_child
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import ExperienceError


def file_contents(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def update_snapshot(root, update):
    path = root / "home/engineering-snapshot.json"
    payload = json.loads(path.read_text())
    update(payload)
    path.write_text(json.dumps(payload))


def test_collection_is_read_only_and_idempotent(workspace_factory, tmp_path):
    workspace = workspace_factory()
    before = file_contents(workspace)
    store = tmp_path / "store"
    first = collect(workspace, store)
    repeated = collect(workspace, store)
    assert (first.status, repeated.status) == ("created", "already_present")
    assert first.case == repeated.case
    assert list_cases(store) == [first.case]
    assert show(first.case.case_id, store) == first.case
    assert file_contents(workspace) == before
    result = verify(first.case.case_id, store)
    assert (result.integrity, result.status) == ("pass", "unknown")
    assert first.case.source.attempt_id is None


def test_rerun_revision_is_distinct_without_inventing_attempts(workspace_factory, tmp_path):
    root = workspace_factory()
    store = tmp_path / "store"
    first = collect(root, store)
    update_snapshot(root, lambda payload: payload.update(workspaceRevision=2))
    second = collect(root, store)
    assert first.case.case_id != second.case.case_id
    assert len(list_cases(store)) == 2
    assert verify(first.case.case_id, store).status == "fail"


@pytest.mark.parametrize("schema", [2, 3, 4])
def test_old_snapshot_is_not_migrated(workspace_factory, tmp_path, schema):
    root = workspace_factory(schema=schema)
    before = file_contents(root)
    result = collect(root, tmp_path / "store")
    assert result.case.source.snapshot_schema == schema
    assert file_contents(root) == before


def test_legacy_without_snapshot_is_explicit_unknown(workspace_factory, tmp_path):
    root = workspace_factory()
    (root / "home/engineering-snapshot.json").unlink()
    before = file_contents(root)
    result = collect(root, tmp_path / "store")
    assert result.case.validation_scope == "legacy_import"
    assert result.case.source.workspace_revision is None
    assert verify(result.case.case_id, tmp_path / "store").status == "unknown"
    assert file_contents(root) == before


def test_corrupt_snapshot_does_not_fall_back_to_legacy(workspace_factory, tmp_path):
    root = workspace_factory()
    (root / "home/engineering-snapshot.json").write_text("{")
    with pytest.raises(ExperienceError, match="invalid Engineering Snapshot"):
        collect(root, tmp_path / "store")
    assert not (tmp_path / "store").exists()


def test_invalid_source_field_is_a_domain_error(workspace_factory, tmp_path):
    root = workspace_factory()
    update_snapshot(root, lambda payload: payload.update(cause=[]))
    with pytest.raises(ExperienceError, match="Malformed workspace evidence"):
        collect(root, tmp_path / "store")


def test_file_digest_rejects_non_file_inputs(tmp_path):
    with pytest.raises(OSError, match="regular file"):
        file_digest(tmp_path)


@pytest.mark.parametrize("mutation", ["corrupt", "deleted", "changed", "symlink"])
def test_verification_detects_source_damage(workspace_factory, tmp_path, mutation):
    root = workspace_factory()
    store = tmp_path / "store"
    result = collect(root, store)
    report = root / "Synthesis_yosys/analysis/qor_metrics.json"
    if mutation == "deleted":
        report.unlink()
    elif mutation == "symlink":
        outside = tmp_path / "outside.json"
        outside.write_bytes(report.read_bytes())
        report.unlink()
        report.symlink_to(outside)
    else:
        report.write_text("{" if mutation == "corrupt" else '{"metrics": []}')
    verification = verify(result.case.case_id, store)
    assert verification.status == "fail"
    assert verification.integrity == "pass"


def test_corrupt_checklist_is_preserved_as_failure(workspace_factory, tmp_path):
    root = workspace_factory()
    checklist = root / "home/checklist.json"
    checklist.write_text("not-json")
    result = collect(root, tmp_path / "store")
    assert checklist.read_text() == "not-json"
    assert verify(result.case.case_id, tmp_path / "store").status == "fail"


def test_report_text_is_opaque_even_with_json_suffix(workspace_factory, tmp_path):
    root = workspace_factory()
    report = root / "Synthesis_yosys/analysis/qor_metrics.json"
    report.write_text("a textual report with a misleading filename")
    update_snapshot(root, lambda payload: payload["artifacts"][0].update(kind="report_text"))
    result = collect(root, tmp_path / "store")
    assert verify(result.case.case_id, tmp_path / "store").status == "unknown"


def test_eda_failure_is_an_observation_not_corrupt_evidence(workspace_factory, tmp_path):
    root = workspace_factory()
    flow = {"steps": [{"name": "STA", "tool": "ecc", "state": "Incomplete"}]}
    (root / "home/flow.json").write_text(json.dumps(flow))
    update_snapshot(root, lambda payload: payload.update(flow=flow, cause="flow_step.failed"))
    result = collect(root, tmp_path / "store")
    assert result.case.facts["flow"] == flow
    assert verify(result.case.case_id, tmp_path / "store").status == "unknown"


def test_snapshot_flow_disagreement_is_rejected(workspace_factory, tmp_path):
    root = workspace_factory()
    (root / "home/flow.json").write_text('{"steps": []}')
    with pytest.raises(ExperienceError, match="does not match"):
        collect(root, tmp_path / "store")


def test_captured_evidence_damage_is_not_hidden_by_idempotence(workspace_factory, tmp_path):
    root = workspace_factory()
    store = tmp_path / "store"
    result = collect(root, store)
    copied = next(item for item in result.case.evidence if item.stored_path)
    path = ExperienceStore(store).case_directory(result.case.case_id) / copied.stored_path
    path.write_text("corrupt")
    assert verify(result.case.case_id, store).integrity == "fail"
    with pytest.raises(ExperienceError, match="corrupt"):
        collect(root, store)


def test_manifest_tampering_is_rejected(workspace_factory, tmp_path):
    result = collect(workspace_factory(), tmp_path / "store")
    directory = ExperienceStore(tmp_path / "store").case_directory(result.case.case_id)
    path = directory / "case.json"
    payload = json.loads(path.read_text())
    payload["source"]["workspace_revision"] = 99
    path.write_text(json.dumps(payload))
    with pytest.raises(ExperienceError, match="identity mismatch"):
        show(result.case.case_id, tmp_path / "store")


@pytest.mark.parametrize("reference", ["../outside", "/absolute", "nested/../../escape", ""])
def test_unsafe_evidence_reference_rejected(tmp_path, reference):
    with pytest.raises(ExperienceError, match="Unsafe"):
        safe_child(tmp_path, reference)


def test_store_and_source_cannot_overlap(workspace_factory, tmp_path):
    root = workspace_factory()
    for store in (root, root / "store", tmp_path):
        with pytest.raises(ExperienceError, match="overlap"):
            collect(root, store)


def test_atomic_write_failure_leaves_no_partial_case(workspace_factory, tmp_path, monkeypatch):
    root = workspace_factory()
    store = tmp_path / "store"
    original = ExperienceStore._write

    def failing_write(path, content):
        if path.name == "case.json":
            raise OSError("disk full")
        original(path, content)

    monkeypatch.setattr(ExperienceStore, "_write", staticmethod(failing_write))
    with pytest.raises(OSError, match="disk full"):
        collect(root, store)
    assert list_cases(store) == []
    assert list(store.iterdir()) == [store / "cases"]


def test_store_writer_conflict_and_symlink_rejected(workspace_factory, tmp_path):
    root = workspace_factory()
    store = tmp_path / "store"
    store.mkdir()
    (store / ".write-lock").mkdir()
    with pytest.raises(ExperienceError, match="collector"):
        collect(root, store)
    (store / ".write-lock").rmdir()
    linked = tmp_path / "linked"
    linked.symlink_to(store, target_is_directory=True)
    with pytest.raises(ExperienceError, match="symlink"):
        collect(root, linked)


def test_missing_source_retains_archive_and_reports_unknown(workspace_factory, tmp_path):
    root = workspace_factory()
    store = tmp_path / "store"
    result = collect(root, store)
    shutil.rmtree(root)
    verification = verify(result.case.case_id, store)
    assert (verification.status, verification.integrity) == ("unknown", "pass")


def test_input_fingerprint_uses_content_not_name_or_path(workspace_factory, tmp_path):
    root = workspace_factory()
    input_file = tmp_path / "original.v"
    input_file.write_text("module sample; endmodule")

    def bind(payload):
        payload["workspaceSpec"] = {
            "design": {"topModule": "sample"},
            "inputs": [{"inputId": "rtl", "role": "rtl"}],
        }
        payload["workspaceBindings"] = {"inputs": {"rtl": str(input_file)}}

    update_snapshot(root, bind)
    first = collect(root, tmp_path / "store").case
    relocated = tmp_path / "renamed.v"
    input_file.rename(relocated)
    input_file = relocated
    update_snapshot(root, bind)
    second = collect(root, tmp_path / "store").case
    assert first.input_content_fingerprint == second.input_content_fingerprint
    input_file.write_text("module sample; wire changed; endmodule")
    third = collect(root, tmp_path / "store").case
    assert second.input_content_fingerprint != third.input_content_fingerprint
    assert third.design_fingerprint is not None
    assert third.design is not None and third.design.fingerprint == third.design_fingerprint
