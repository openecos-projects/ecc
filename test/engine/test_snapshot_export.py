import json
import os
from types import SimpleNamespace

import pytest

from chipcompiler.engine.snapshot import (
    EngineeringSnapshotError,
    create_engineering_snapshot,
    read_engineering_snapshot_file,
)
from chipcompiler.engine.snapshot_export import SnapshotDestinationError, save_engineering_snapshot


@pytest.fixture
def committed_snapshot(tmp_path):
    root = tmp_path / "source"
    (root / "home").mkdir(parents=True)
    workspace = SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(data={"steps": []}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )
    snapshot = create_engineering_snapshot(workspace, workspace_id="snapshot-gcd")
    return root, snapshot


def _files(root):
    return {
        path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("schema_version", [2, 3, 4])
def test_export_preserves_snapshot_and_workspace(committed_snapshot, tmp_path, schema_version):
    root, snapshot = committed_snapshot
    snapshot["schemaVersion"] = schema_version
    snapshot["parameters"]["label"] = "设计比较"
    source = root / "home" / "engineering-snapshot.json"
    source.write_text(json.dumps(snapshot), encoding="utf-8")
    before = _files(root)
    destination = tmp_path / "saved.json"

    saved = save_engineering_snapshot(root, destination)

    assert read_engineering_snapshot_file(destination) == snapshot
    assert saved.path == destination
    assert saved.source == source
    assert (saved.schema_version, saved.workspace_id, saved.workspace_revision) == (
        schema_version,
        snapshot["workspaceId"],
        snapshot["workspaceRevision"],
    )
    assert saved.bytes_written == destination.stat().st_size
    assert _files(root) == before
    assert not list(tmp_path.glob(".ecc-snapshot-*"))


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "dangling_symlink"])
def test_existing_destination_is_never_overwritten(committed_snapshot, tmp_path, kind):
    root, _snapshot = committed_snapshot
    destination = tmp_path / "saved.json"
    original = tmp_path / "original.json"
    original.write_text("keep me")
    if kind == "file":
        destination.write_text("keep destination")
    elif kind == "directory":
        destination.mkdir()
    else:
        destination.symlink_to(original if kind == "symlink" else tmp_path / "missing.json")
    before = _files(root)

    with pytest.raises(FileExistsError):
        save_engineering_snapshot(root, destination)

    assert original.read_text() == "keep me"
    assert os.path.lexists(destination)
    if kind == "file":
        assert destination.read_text() == "keep destination"
    elif "symlink" in kind:
        assert destination.is_symlink()
    assert _files(root) == before
    assert not list(tmp_path.glob(".ecc-snapshot-*"))


@pytest.mark.parametrize(
    "relative", ["saved.json", "home/saved.json", "home/engineering-snapshot.json"]
)
def test_workspace_destination_is_rejected(committed_snapshot, relative):
    root, _snapshot = committed_snapshot
    before = _files(root)

    with pytest.raises(SnapshotDestinationError, match="outside"):
        save_engineering_snapshot(root, root / relative)

    assert _files(root) == before


def test_parent_symlink_into_workspace_is_rejected(committed_snapshot, tmp_path):
    root, _snapshot = committed_snapshot
    alias = tmp_path / "alias"
    alias.symlink_to(root / "home", target_is_directory=True)
    before = _files(root)

    with pytest.raises(SnapshotDestinationError, match="outside"):
        save_engineering_snapshot(root, alias / "saved.json")

    assert _files(root) == before


@pytest.mark.parametrize(
    "kind", ["missing_parent", "file_parent", "loop_parent", "compressed", "empty"]
)
def test_invalid_destination_has_no_side_effects(committed_snapshot, tmp_path, kind):
    root, _snapshot = committed_snapshot
    if kind == "missing_parent":
        destination = tmp_path / "missing" / "saved.json"
    elif kind == "file_parent":
        parent = tmp_path / "not_a_directory"
        parent.write_text("keep")
        destination = parent / "saved.json"
    elif kind == "loop_parent":
        parent = tmp_path / "loop"
        parent.symlink_to(parent)
        destination = parent / "saved.json"
    else:
        destination = tmp_path / "saved.json.gz" if kind == "compressed" else ""
    before = _files(root)

    with pytest.raises(SnapshotDestinationError):
        save_engineering_snapshot(root, destination)

    assert _files(root) == before
    assert not (tmp_path / "missing").exists()
    assert not list(tmp_path.glob(".ecc-snapshot-*"))


@pytest.mark.parametrize("payload", [None, "{", "[]", '{"schemaVersion":999}'])
def test_missing_or_corrupt_snapshot_creates_no_output(committed_snapshot, tmp_path, payload):
    root, _snapshot = committed_snapshot
    source = root / "home" / "engineering-snapshot.json"
    if payload is None:
        source.unlink()
    else:
        source.write_text(payload)
    before = _files(root)
    destination = tmp_path / "saved.json"

    with pytest.raises(EngineeringSnapshotError):
        save_engineering_snapshot(root, destination)

    assert _files(root) == before
    assert not destination.exists()
    assert not list(tmp_path.glob(".ecc-snapshot-*"))


def test_export_checks_workspace_identity(committed_snapshot, tmp_path):
    root, _snapshot = committed_snapshot
    (root / "home" / "workspace-commands.json").write_text(
        json.dumps({"commands": {"id": {"result": {"workspaceId": "different-workspace"}}}})
    )

    with pytest.raises(EngineeringSnapshotError, match="identity mismatch"):
        save_engineering_snapshot(root, tmp_path / "saved.json")

    assert not (tmp_path / "saved.json").exists()


@pytest.mark.parametrize("module", ["snapshot", "snapshot_export"])
def test_read_and_write_size_limits_create_no_output(
    committed_snapshot, tmp_path, monkeypatch, module
):
    root, _snapshot = committed_snapshot
    monkeypatch.setattr(f"chipcompiler.engine.{module}.ENGINEERING_SNAPSHOT_MAX_BYTES", 16)

    with pytest.raises(EngineeringSnapshotError, match="oversized|size limit"):
        save_engineering_snapshot(root, tmp_path / "saved.json")

    assert not (tmp_path / "saved.json").exists()
    assert not list(tmp_path.glob(".ecc-snapshot-*"))


def test_relative_output_uses_current_directory(committed_snapshot, tmp_path, monkeypatch):
    root, snapshot = committed_snapshot
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    monkeypatch.chdir(output_dir)

    saved = save_engineering_snapshot(root, "saved.json")

    assert saved.path == output_dir / "saved.json"
    assert read_engineering_snapshot_file(saved.path) == snapshot


def test_external_parent_symlink_is_resolved(committed_snapshot, tmp_path):
    root, snapshot = committed_snapshot
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(output_dir, target_is_directory=True)

    saved = save_engineering_snapshot(root, alias / "saved.json")

    assert saved.path == output_dir / "saved.json"
    assert read_engineering_snapshot_file(saved.path) == snapshot


@pytest.mark.parametrize("operation", ["mkstemp", "fsync", "link"])
def test_io_failures_remove_temporary_files(committed_snapshot, tmp_path, monkeypatch, operation):
    root, _snapshot = committed_snapshot
    before = _files(root)

    def fail(*args, **kwargs):
        raise OSError("injected failure")

    module = "tempfile" if operation == "mkstemp" else "os"
    monkeypatch.setattr(f"chipcompiler.engine.snapshot_export.{module}.{operation}", fail)

    with pytest.raises(OSError, match="injected failure"):
        save_engineering_snapshot(root, tmp_path / "saved.json")

    assert _files(root) == before
    assert not (tmp_path / "saved.json").exists()
    assert not list(tmp_path.glob(".ecc-snapshot-*"))


def test_concurrently_created_destination_is_preserved(committed_snapshot, tmp_path, monkeypatch):
    root, _snapshot = committed_snapshot
    destination = tmp_path / "saved.json"
    real_link = os.link

    def race(source, target):
        destination.write_text("created concurrently")
        return real_link(source, target)

    monkeypatch.setattr("chipcompiler.engine.snapshot_export.os.link", race)

    with pytest.raises(FileExistsError):
        save_engineering_snapshot(root, destination)

    assert destination.read_text() == "created concurrently"
    assert not list(tmp_path.glob(".ecc-snapshot-*"))
