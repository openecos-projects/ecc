"""Structured IR publication binds values to the producing geometry snapshot."""

import hashlib
import json

import pytest

from chipcompiler.tools.ecc.emir_artifacts import discard_ir_snapshot, publish_ir_snapshot


def source(tmp_path):
    data = tmp_path / "data"
    report = data / "emir_reporter/ir_drop.json"
    report.parent.mkdir(parents=True)
    payload = {
        "schema": "ecos.emir.ir.v1",
        "coordinate_unit": "dbu",
        "dbu_per_micron": 1000,
        "views": [],
    }
    report.write_text(json.dumps(payload))
    manifest = tmp_path / "geometry/geometry.manifest"
    manifest.parent.mkdir()
    manifest.write_text("schema_version=1\ndbu_per_micron=1000\n")
    return data, manifest, payload


def test_ir_snapshot_preserves_structured_values_and_binds_geometry(tmp_path):
    data, manifest, payload = source(tmp_path)
    publish_ir_snapshot(data, manifest)
    target = manifest.parent / "ir/ir_drop.json"
    assert json.loads(target.read_text()) == {
        **payload,
        "geometry_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    }
    discard_ir_snapshot(data, manifest)
    assert not target.exists()
    assert not (data / "emir_reporter/ir_drop.json").exists()
    # Old runtimes and failed reruns cannot resurrect the previous result.
    publish_ir_snapshot(data, manifest)
    assert not target.exists()


def test_ir_snapshot_rejects_mismatched_units_without_publishing(tmp_path):
    data, manifest, _ = source(tmp_path)
    manifest.write_text("dbu_per_micron=2000\n")
    with pytest.raises(ValueError, match="units"):
        publish_ir_snapshot(data, manifest)
    assert not (manifest.parent / "ir/ir_drop.json").exists()
