import hashlib
import io
import json
import shutil
import tarfile

import pytest

from ecc_experience.api import collect, package_export, package_import, show, verify
from ecc_experience.files import canonical_bytes, case_identity
from ecc_experience.knowledge.package_archive import build_manifest, read_archive, write_archive
from ecc_experience.knowledge.release import create_release, verify_release
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import ExperienceError
from test.experience.test_release import _prepare_workspace


@pytest.fixture
def transfer_case(workspace_factory, tmp_path):
    workspace = workspace_factory()
    case = collect(workspace, tmp_path / "source-store").case
    return case, workspace


def _export(tmp_path, case_ids):
    package = tmp_path / "experience.tar.gz"
    result = package_export(tmp_path / "source-store", package, case_ids=case_ids)
    return package, result


def _rewrite(package, entries):
    with tarfile.open(package, "w:gz") as archive:
        for name, content in entries:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))


def test_round_trip_preserves_cases_and_is_idempotent(transfer_case, tmp_path):
    case, workspace = transfer_case
    source_files = {path: path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
    package, exported = _export(tmp_path, [case.case_id])
    target = tmp_path / "target-store"

    imported = package_import(package, target)
    repeated = package_import(package, target)

    assert imported["package_id"] == exported["package_id"]
    assert (imported["status"], imported["created_count"], imported["integrity"]) == (
        "imported",
        1,
        "pass",
    )
    assert (repeated["status"], repeated["already_present_count"]) == ("already_present", 1)
    assert show(case.case_id, target) == case
    assert verify(case.case_id, target) == verify(case.case_id, tmp_path / "source-store")
    assert source_files == {
        path: path.read_bytes() for path in workspace.rglob("*") if path.is_file()
    }
    assert (
        package_export(tmp_path / "source-store", package, case_ids=[case.case_id])["status"]
        == "already_present"
    )


def test_export_is_deterministic_and_does_not_follow_source_files(transfer_case, tmp_path):
    case, workspace = transfer_case
    package, exported = _export(tmp_path, [case.case_id])
    shutil.rmtree(workspace)
    other = tmp_path / "other.tar.gz"
    package_export(tmp_path / "source-store", other, case_ids=[case.case_id])
    assert package.read_bytes() == other.read_bytes()
    imported = package_import(other, tmp_path / "target-store")
    assert imported["package_id"] == exported["package_id"]
    assert imported["source_verification"] == "not_performed"
    verification = verify(case.case_id, tmp_path / "target-store")
    assert (verification.integrity, verification.status) == ("pass", "unknown")


def test_release_round_trip_preserves_release_verification(workspace_factory, tmp_path):
    from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
    from ecc_experience.collection.collect import collect_committed_case

    workspace = workspace_factory()
    rtl = tmp_path / "input.v"
    rtl.write_text("module sample; endmodule")
    _prepare_workspace(workspace, rtl)
    source = tmp_path / "source-store"
    case = collect_committed_case(
        workspace,
        ExperienceStore(source),
        read_workspace_observation,
        attempt_id="attempt-transfer",
    ).case
    release = tmp_path / "release.json"
    create_release([case.case_id], source, release)
    package = tmp_path / "release.tar.gz"
    package_export(source, package, release=release)
    target = tmp_path / "target-store"

    result = package_import(package, target)

    assert verify_release(result["release"]["path"], target)["status"] == "pass"
    assert package_import(package, target)["release"]["status"] == "already_present"
    assert json.loads(release.read_text()) == json.loads(
        (target / "releases" / f"{result['release']['release_id']}.json").read_text()
    )
    shutil.rmtree(workspace)
    assert verify_release(result["release"]["path"], target)["status"] == "unknown"


@pytest.mark.parametrize(
    "selection", [{}, {"case_ids": []}, {"case_ids": ["bad"], "release": "bad"}]
)
def test_export_requires_explicit_unambiguous_selection(tmp_path, selection):
    with pytest.raises(ExperienceError) as raised:
        package_export(tmp_path / "source", tmp_path / "out.tar.gz", **selection)
    assert raised.value.code == "experience_package_selection_invalid"


def test_duplicate_selection_is_rejected_without_output(transfer_case, tmp_path):
    case, _workspace = transfer_case
    with pytest.raises(ExperienceError):
        _export(tmp_path, [case.case_id, case.case_id])
    assert not (tmp_path / "experience.tar.gz").exists()


@pytest.mark.parametrize(
    "damage",
    ["checksum", "missing", "extra", "duplicate", "identity", "case_identity", "case_evidence"],
)
def test_invalid_package_is_rejected_before_store_creation(transfer_case, tmp_path, damage):
    case, _workspace = transfer_case
    package, _exported = _export(tmp_path, [case.case_id])
    manifest, files = read_archive(package)
    if damage == "checksum":
        first = next(iter(files))
        files[first] += b" "
    elif damage == "missing":
        files.pop(next(iter(files)))
    elif damage == "extra":
        files["extra"] = b"undeclared"
    elif damage == "identity":
        manifest = manifest.model_copy(update={"package_id": "package-incorrect"})
    elif damage in {"case_identity", "case_evidence"}:
        reference = f"cases/{case.case_id}/case.json"
        payload = json.loads(files[reference])
        if damage == "case_identity":
            payload["facts"]["unexpected"] = True
        else:
            evidence = next(item for item in payload["evidence"] if item["stored_path"])
            evidence["sha256"] = "0" * 64
            new_id = case_identity(payload)
            payload["case_id"] = new_id
            files = {name.replace(case.case_id, new_id): content for name, content in files.items()}
            reference = reference.replace(case.case_id, new_id)
        files[reference] = canonical_bytes(payload)
        selected = [payload["case_id"]]
        manifest = build_manifest(files, selected)
    entries = [("manifest.json", canonical_bytes(manifest.model_dump())), *files.items()]
    if damage == "duplicate":
        entries.append(entries[-1])
    _rewrite(package, entries)
    target = tmp_path / "target-store"
    with pytest.raises(ExperienceError) as raised:
        package_import(package, target)
    assert raised.value.code == "experience_package_invalid"
    assert not target.exists()


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "/absolute",
        "cases/../outside",
        "C:/file",
        "cases\\file",
        "./manifest.json",
        "a//b",
    ],
)
def test_unsafe_archive_paths_are_rejected(tmp_path, name):
    package = tmp_path / "unsafe.tar.gz"
    _rewrite(package, [(name, b"data")])
    with pytest.raises(ExperienceError) as raised:
        package_import(package, tmp_path / "target-store")
    assert raised.value.code == "experience_package_invalid"
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.FIFOTYPE]
)
def test_non_regular_archive_entries_are_rejected(tmp_path, kind):
    package = tmp_path / "unsafe.tar.gz"
    with tarfile.open(package, "w:gz") as archive:
        member = tarfile.TarInfo("manifest.json")
        member.type = kind
        member.linkname = "../outside"
        archive.addfile(member)
    with pytest.raises(ExperienceError):
        package_import(package, tmp_path / "target-store")


def test_corrupt_existing_case_prevents_all_new_publication(
    transfer_case, workspace_factory, tmp_path
):
    first, _workspace = transfer_case
    second = collect(workspace_factory("second"), tmp_path / "source-store").case
    package, _exported = _export(tmp_path, [first.case_id, second.case_id])
    target = tmp_path / "target-store"
    first_package = tmp_path / "first.tar.gz"
    package_export(tmp_path / "source-store", first_package, case_ids=[first.case_id])
    package_import(first_package, target)
    directory = ExperienceStore(target).case_directory(first.case_id)
    evidence = next(item for item in first.evidence if item.stored_path)
    (directory / evidence.stored_path).write_bytes(b"corrupt")

    with pytest.raises(ExperienceError, match="corrupt"):
        package_import(package, target)

    assert ExperienceStore(target).list_ids() == [first.case_id]
    assert (directory / evidence.stored_path).read_bytes() == b"corrupt"


def test_mid_publication_failure_rolls_back_new_cases(
    transfer_case, workspace_factory, tmp_path, monkeypatch
):
    from ecc_experience.knowledge import store as store_module

    first, _workspace = transfer_case
    second = collect(workspace_factory("second"), tmp_path / "source-store").case
    package, _exported = _export(tmp_path, [first.case_id, second.case_id])
    target = tmp_path / "target-store"
    original = store_module.os.rename
    calls = []

    def fail_second(source, destination):
        calls.append(destination)
        if len(calls) == 2:
            raise OSError("simulated full disk")
        original(source, destination)

    monkeypatch.setattr(store_module.os, "rename", fail_second)
    with pytest.raises(OSError, match="full disk"):
        package_import(package, target)
    assert ExperienceStore(target).list_ids() == []
    assert not (target / ".write-lock").exists()
    assert not list(target.glob(".collect-*"))


def test_symlink_destination_and_busy_store_preserve_existing_files(transfer_case, tmp_path):
    case, _workspace = transfer_case
    package, _exported = _export(tmp_path, [case.case_id])
    target = tmp_path / "target-store"
    target.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (target / "cases").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ExperienceError, match="Symlink"):
        package_import(package, target)
    assert list(outside.iterdir()) == []
    (target / "cases").unlink()
    (target / ".write-lock").mkdir()
    with pytest.raises(ExperienceError) as raised:
        package_import(package, target)
    assert raised.value.code == "experience_store_busy"


def test_output_collision_is_not_overwritten(transfer_case, tmp_path):
    case, _workspace = transfer_case
    package, _exported = _export(tmp_path, [case.case_id])
    original = hashlib.sha256(package.read_bytes()).hexdigest()
    manifest, files = read_archive(package)
    other = manifest.model_copy(update={"release_path": "release.json"})
    with pytest.raises(ExperienceError) as raised:
        write_archive(package, other, files)
    assert raised.value.code == "experience_package_conflict"
    assert hashlib.sha256(package.read_bytes()).hexdigest() == original


@pytest.mark.parametrize(
    "limit", ["MAX_ARCHIVE_BYTES", "MAX_FILE_BYTES", "MAX_TOTAL_BYTES", "MAX_FILES"]
)
def test_resource_limits_reject_before_import(transfer_case, tmp_path, monkeypatch, limit):
    from ecc_experience.knowledge import package_archive

    case, _workspace = transfer_case
    package, _exported = _export(tmp_path, [case.case_id])
    monkeypatch.setattr(package_archive, limit, 1)
    target = tmp_path / "target-store"
    with pytest.raises(ExperienceError) as raised:
        package_import(package, target)
    assert raised.value.code == "experience_package_invalid"
    assert not target.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_schema",
        "boolean_schema",
        "new_schema",
        "bad_json",
        "duplicate_files",
        "duplicate_cases",
    ],
)
def test_invalid_manifest_is_rejected(transfer_case, tmp_path, mutation):
    case, _workspace = transfer_case
    package, _exported = _export(tmp_path, [case.case_id])
    manifest, files = read_archive(package)
    payload = manifest.model_dump()
    if mutation == "missing_schema":
        del payload["schema_version"]
    elif mutation == "boolean_schema":
        payload["schema_version"] = True
    elif mutation == "new_schema":
        payload["schema_version"] = 2
    elif mutation == "duplicate_files":
        payload["files"].append(payload["files"][0])
    elif mutation == "duplicate_cases":
        payload["case_ids"].append(case.case_id)
    if mutation in {"duplicate_files", "duplicate_cases"}:
        from ecc_experience.files import digest

        payload["package_id"] = "package-" + digest(
            {key: value for key, value in payload.items() if key != "package_id"}
        )
    content = b"{" if mutation == "bad_json" else canonical_bytes(payload)
    _rewrite(package, [("manifest.json", content), *files.items()])
    with pytest.raises(ExperienceError):
        package_import(package, tmp_path / "target-store")


def test_truncated_gzip_footer_is_not_accepted(transfer_case, tmp_path):
    case, _workspace = transfer_case
    package, _exported = _export(tmp_path, [case.case_id])
    package.write_bytes(package.read_bytes()[:-8])
    with pytest.raises(ExperienceError) as raised:
        package_import(package, tmp_path / "target-store")
    assert raised.value.code == "experience_package_invalid"


def test_packaged_release_metadata_must_match_case(workspace_factory, tmp_path):
    workspace = workspace_factory()
    rtl = tmp_path / "input.v"
    rtl.write_text("module sample; endmodule")
    _prepare_workspace(workspace, rtl)
    case = collect(workspace, tmp_path / "source-store").case
    package, _exported = _export(tmp_path, [case.case_id])
    _manifest, files = read_archive(package)
    from ecc_experience.files import digest
    from ecc_experience.knowledge.release import RELEASE_SCHEMA, case_record

    record = case_record(case, {"status": "pass", "integrity": "pass"})
    record["qor_score"] = 999
    identity = {"schema": RELEASE_SCHEMA, "cases": [record]}
    release = {
        **identity,
        "release_id": "release-" + digest(identity),
        "created_at": "test",
        "policy": {
            "requires_verified_cases": True,
            "requires_complete_input_fingerprint": True,
            "auto_apply": False,
        },
    }
    files["release.json"] = canonical_bytes(release)
    manifest = build_manifest(files, [case.case_id])
    _rewrite(package, [("manifest.json", canonical_bytes(manifest.model_dump())), *files.items()])
    with pytest.raises(ExperienceError, match="release"):
        package_import(package, tmp_path / "target-store")
    assert not (tmp_path / "target-store").exists()


def test_release_conflict_preserves_existing_data_without_importing_cases(
    workspace_factory, tmp_path
):
    from ecc_experience.files import digest
    from ecc_experience.knowledge.release import RELEASE_SCHEMA, case_record

    workspace = workspace_factory()
    rtl = tmp_path / "input.v"
    rtl.write_text("module sample; endmodule")
    _prepare_workspace(workspace, rtl)
    case = collect(workspace, tmp_path / "source-store").case
    package, _exported = _export(tmp_path, [case.case_id])
    _manifest, files = read_archive(package)
    identity = {
        "schema": RELEASE_SCHEMA,
        "cases": [case_record(case, {"status": "pass", "integrity": "pass"})],
    }
    release = {
        **identity,
        "release_id": "release-" + digest(identity),
        "created_at": "test",
        "policy": {
            "requires_verified_cases": True,
            "requires_complete_input_fingerprint": True,
            "auto_apply": False,
        },
    }
    files["release.json"] = canonical_bytes(release)
    manifest = build_manifest(files, [case.case_id])
    _rewrite(package, [("manifest.json", canonical_bytes(manifest.model_dump())), *files.items()])
    target = tmp_path / "target-store"
    release_file = target / "releases" / f"{release['release_id']}.json"
    release_file.parent.mkdir(parents=True)
    release_file.write_text('{"existing": true}')

    with pytest.raises(ExperienceError) as raised:
        package_import(package, target)

    assert raised.value.code == "experience_release_conflict"
    assert release_file.read_text() == '{"existing": true}'
    assert ExperienceStore(target).list_ids() == []


def test_package_paths_cannot_overlap_store(transfer_case, tmp_path):
    case, _workspace = transfer_case
    source = tmp_path / "source-store"
    with pytest.raises(ExperienceError) as raised:
        package_export(source, source / "inside.tar.gz", case_ids=[case.case_id])
    assert raised.value.code == "experience_package_selection_invalid"
    package, _exported = _export(tmp_path, [case.case_id])
    with pytest.raises(ExperienceError) as raised:
        package_import(package, tmp_path)
    assert raised.value.code == "experience_package_selection_invalid"
