import json

import pytest

from chipcompiler.engine.snapshot import (
    LEGACY_SNAPSHOT_SCHEMA_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    SNAPSHOT_V3_SCHEMA_VERSION,
    SNAPSHOT_V4_SCHEMA_VERSION,
    EngineeringSnapshotError,
    read_engineering_snapshot_file,
    read_engineering_snapshot_from_directory,
)
from chipcompiler.engine.snapshot_qor import unavailable_qor_snapshot_extension


@pytest.fixture
def snapshot_file(tmp_path):
    snapshot = {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "workspaceId": "archived-gcd",
        "workspaceRevision": 1,
        "flow": {"steps": []},
        "parameters": {},
        "checklist": {},
        "signoffAssessment": {},
        "analysis": {},
        "qorAssessment": {"metrics": []},
        "metrics": [],
        "qorSnapshotExtension": unavailable_qor_snapshot_extension("no reports"),
        "timingPreview": {},
        "hotspotPreview": {},
        "workspaceSpec": {},
        "workspaceBindings": {},
        "stepOutputs": {"directory": ".", "design": "gcd", "steps": []},
        "artifacts": [],
    }
    path = tmp_path / "archive" / "saved.json"
    path.parent.mkdir()
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    return path, snapshot


@pytest.mark.parametrize(
    "schema_version",
    [
        LEGACY_SNAPSHOT_SCHEMA_VERSION,
        SNAPSHOT_V3_SCHEMA_VERSION,
        SNAPSHOT_V4_SCHEMA_VERSION,
        SNAPSHOT_SCHEMA_VERSION,
    ],
)
def test_file_reader_supports_existing_schemas_without_migration(snapshot_file, schema_version):
    path, snapshot = snapshot_file
    snapshot["schemaVersion"] = schema_version
    path.write_text(json.dumps(snapshot))
    original = path.read_bytes()

    assert read_engineering_snapshot_file(path) == snapshot
    assert path.read_bytes() == original


@pytest.mark.parametrize("schema_version", [[], {}, None, True, "4", 4.0, 999])
def test_invalid_schema_version_is_a_snapshot_error(snapshot_file, schema_version):
    path, snapshot = snapshot_file
    snapshot["schemaVersion"] = schema_version
    path.write_text(json.dumps(snapshot))

    with pytest.raises(EngineeringSnapshotError, match="schemaVersion"):
        read_engineering_snapshot_file(path)


@pytest.mark.parametrize("section", ["workspaceSpec", "workspaceBindings", "qorSnapshotExtension"])
def test_invalid_optional_legacy_sections_are_rejected(snapshot_file, section):
    path, snapshot = snapshot_file
    snapshot["schemaVersion"] = LEGACY_SNAPSHOT_SCHEMA_VERSION
    snapshot[section] = []
    path.write_text(json.dumps(snapshot))

    with pytest.raises(EngineeringSnapshotError, match=section):
        read_engineering_snapshot_file(path)


def test_saved_snapshot_identity_does_not_depend_on_adjacent_workspace_commands(snapshot_file):
    path, snapshot = snapshot_file
    home = path.parent.parent / "home"
    home.mkdir()
    (home / "workspace-commands.json").write_text(
        json.dumps({"commands": {"id": {"result": {"workspaceId": "unrelated-workspace"}}}})
    )
    (home / "engineering-snapshot.json").write_text(json.dumps(snapshot))

    assert read_engineering_snapshot_file(path) == snapshot
    with pytest.raises(EngineeringSnapshotError, match="identity mismatch"):
        read_engineering_snapshot_from_directory(home.parent)


def test_oversized_file_is_rejected_before_json_read(snapshot_file, monkeypatch):
    path, _snapshot = snapshot_file
    monkeypatch.setattr("chipcompiler.engine.snapshot.ENGINEERING_SNAPSHOT_MAX_BYTES", 16)

    def unexpected_parse(*args, **kwargs):
        pytest.fail("oversized input must not be parsed")

    monkeypatch.setattr("chipcompiler.engine.snapshot.json.loads", unexpected_parse)

    with pytest.raises(EngineeringSnapshotError, match="oversized"):
        read_engineering_snapshot_file(path)


def test_non_utf8_snapshot_returns_a_snapshot_error(snapshot_file):
    path, snapshot = snapshot_file
    path.write_bytes(json.dumps(snapshot).encode("utf-16"))

    with pytest.raises(EngineeringSnapshotError, match="invalid"):
        read_engineering_snapshot_file(path)


def test_compressed_file_is_not_decompressed(snapshot_file):
    path, _snapshot = snapshot_file

    with pytest.raises(EngineeringSnapshotError, match="uncompressed JSON"):
        read_engineering_snapshot_file(path.with_suffix(".gz"))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_json_values_are_rejected(snapshot_file, value):
    path, snapshot = snapshot_file
    snapshot["parameters"]["nonfinite"] = value
    path.write_text(json.dumps(snapshot))

    with pytest.raises(EngineeringSnapshotError, match="non-finite"):
        read_engineering_snapshot_file(path)


def test_excessive_json_nesting_returns_a_snapshot_error(snapshot_file):
    path, _snapshot = snapshot_file
    path.write_text('{"nested":' + "[" * 2000 + "0" + "]" * 2000 + "}")

    with pytest.raises(EngineeringSnapshotError, match="invalid"):
        read_engineering_snapshot_file(path)


def test_symlink_loop_returns_a_snapshot_error(tmp_path):
    path = tmp_path / "loop.json"
    path.symlink_to(path.name)

    with pytest.raises(EngineeringSnapshotError, match="invalid"):
        read_engineering_snapshot_file(path)


def test_unsafe_artifact_reference_remains_rejected(snapshot_file):
    path, snapshot = snapshot_file
    snapshot["artifacts"] = [
        {"artifactId": "path-id", "reference": "../outside.gds", "availability": "available"}
    ]
    path.write_text(json.dumps(snapshot))

    with pytest.raises(EngineeringSnapshotError, match="artifact reference"):
        read_engineering_snapshot_file(path)


def test_oversized_qor_integer_returns_a_snapshot_error(snapshot_file):
    path, snapshot = snapshot_file
    snapshot["qorSnapshotExtension"]["score"] = 10**400
    path.write_text(json.dumps(snapshot))

    with pytest.raises(EngineeringSnapshotError, match="invalid"):
        read_engineering_snapshot_file(path)


def test_unhashable_artifact_availability_returns_a_snapshot_error(snapshot_file):
    from chipcompiler.engine.snapshot import _artifact_id

    path, snapshot = snapshot_file
    reference = "output/design.gds"
    snapshot["artifacts"] = [
        {
            "artifactId": _artifact_id(snapshot["workspaceId"], reference),
            "reference": reference,
            "availability": [],
        }
    ]
    path.write_text(json.dumps(snapshot))

    with pytest.raises(EngineeringSnapshotError, match="invalid"):
        read_engineering_snapshot_file(path)
