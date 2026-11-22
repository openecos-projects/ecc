"""Native display publication binds immutable, validated files to one snapshot."""

import json
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.data import EccOutput, EccStep, Workspace
from chipcompiler.tools.geometry_display import HEADER, begin, invalidate, metadata, publish
from chipcompiler.tools.replay_artifacts import reference_geometry


def asset(path, *, key="power:total", kind="power", dbu=1000, records=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    info = {"kind": kind, "key": key, "label": "Total power", "dbu_per_micron": dbu}
    data = json.dumps(info).encode()
    if records:
        # Independent MessagePack maps; publisher validates offsets, never decodes samples.
        body = b"\x80\x80" + struct.pack("<QQQ", 0, 1, 2)
        header = HEADER.pack(b"ECOSDSP1", 1, 2, len(data), 0, 2, 40 + len(data) + 2)
    else:
        body = struct.pack("<IIiiiid", 0, 0, -10, 20, 30, 40, 0.001)
        header = HEADER.pack(b"ECOSDSP1", 1, 1, len(data), 32, 1, 0)
    path.write_bytes(header + data + body)
    return info


def step_at(root):
    manifest = root / "output/geometry/geometry.manifest"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("schema_version=1\ndbu_per_micron=1000\n")
    return SimpleNamespace(
        name="powerAnalysis",
        directory=str(root),
        output=SimpleNamespace(geometry_manifest=str(manifest)),
    )


def published(step):
    manifest = Path(step.output.geometry_manifest)
    return [
        manifest.parent / line.split("=", 1)[1]
        for line in manifest.read_text().splitlines()
        if line.startswith("display.")
    ]


@pytest.mark.parametrize("failure", ["begin", "publish"])
def test_display_failure_does_not_fail_step_with_replay_off(tmp_path, monkeypatch, failure):
    from chipcompiler.tools import eda, geometry_display

    workspace = Workspace(directory=tmp_path)
    workspace.parameters.data["replay"] = {"enabled": False}
    manifest = Path(step_at(tmp_path).output.geometry_manifest)
    step = EccStep(
        name="powerAnalysis", directory=tmp_path, output=EccOutput(geometry_manifest=manifest)
    )
    monkeypatch.setattr(eda, "_run_step", lambda *_: True)

    def fail(*_):
        raise OSError("display write failed")

    monkeypatch.setattr(geometry_display, failure, fail)
    assert eda.run_step(workspace, step) is True


def test_publication_is_immutable_and_replay_fingerprints_assets(tmp_path):
    step = step_at(tmp_path)
    source = tmp_path / "data/power.gdisplay"
    expected = asset(source)
    publish(step, 0)
    first = published(step)[0]
    original = first.read_bytes()
    assert metadata(first) == expected
    reference = reference_geometry(Path(step.output.geometry_manifest))["shared_geometry"]
    assert first.relative_to(first.parents[2]).as_posix() in reference["files"]
    invalidate(step)
    assert published(step) == [] and first.read_bytes() == original
    asset(source, key="power:leakage")
    publish(step, 0)
    assert published(step)[0] != first and first.read_bytes() == original


def test_stale_files_and_duplicate_copies_are_not_published(tmp_path):
    step = step_at(tmp_path)
    stale = tmp_path / "data/stale.gdisplay"
    asset(stale)
    os.utime(stale, ns=(1, 1))
    source = tmp_path / "data/current.gdisplay"
    asset(source, key="current")
    duplicate = tmp_path / "feature/current.gdisplay"
    duplicate.parent.mkdir()
    duplicate.write_bytes(source.read_bytes())
    publish(step, 2)
    assert [metadata(p)["key"] for p in published(step)] == ["current"]


def test_conflicts_and_units_fail_without_changing_manifest(tmp_path):
    step = step_at(tmp_path)
    source = tmp_path / "data/a.gdisplay"
    asset(source)
    publish(step, 0)
    manifest = Path(step.output.geometry_manifest)
    before = manifest.read_bytes()
    asset(tmp_path / "data/b.gdisplay", dbu=2000)
    with pytest.raises(ValueError, match="Duplicate"):
        publish(step, 0)
    assert manifest.read_bytes() == before
    asset(tmp_path / "data/b.gdisplay", key="different", dbu=2000)
    with pytest.raises(ValueError, match="unit mismatch"):
        publish(step, 0)
    assert manifest.read_bytes() == before


def test_publish_rejects_symlink_escape(tmp_path):
    step = step_at(tmp_path / "step")
    external = tmp_path / "outside.gdisplay"
    asset(external)
    target = Path(step.directory) / "data/escape.gdisplay"
    target.parent.mkdir()
    target.symlink_to(external)
    with pytest.raises(ValueError):
        publish(step, 0)


def test_records_validate_every_offset_and_truncation(tmp_path):
    path = tmp_path / "records.gdisplay"
    expected = asset(path, records=True)
    assert metadata(path, validate_index=True) == expected
    data = bytearray(path.read_bytes())
    struct.pack_into("<Q", data, len(data) - 16, 3)
    path.write_bytes(data)
    with pytest.raises(ValueError, match="offset"):
        metadata(path, validate_index=True)
    path.write_bytes(data[:-1])
    with pytest.raises(ValueError, match="size/index"):
        metadata(path, validate_index=True)


def test_copy_failure_keeps_old_manifest_and_removes_partial_publication(tmp_path, monkeypatch):
    step = step_at(tmp_path)
    asset(tmp_path / "data/a.gdisplay")
    publish(step, 0)
    manifest = Path(step.output.geometry_manifest)
    before = manifest.read_bytes()
    directories = list((manifest.parent / "display").iterdir())

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("chipcompiler.tools.geometry_display.shutil.copyfile", fail)
    with pytest.raises(OSError, match="disk full"):
        publish(step, 0)
    assert manifest.read_bytes() == before
    assert list((manifest.parent / "display").iterdir()) == directories


def test_replay_index_reuses_geometry_without_opening_large_text_report(tmp_path):
    from chipcompiler.tools.replay_analysis import collect_analysis

    step = step_at(tmp_path)
    step.name = "powerAnalysis"
    asset(tmp_path / "data/power.gdisplay")
    publish(step, 0)
    text_report = tmp_path / "data/pw/power_reporter/instance_power.tsv"
    text_report.parent.mkdir(parents=True)
    text_report.write_text("invalid legacy report: must not be decoded")
    attempt = tmp_path / "attempt"
    result = collect_analysis(step, attempt, 0)
    assert result == {
        "analysis": "subflows/analysis/overlays/index.json",
        "analysis_view_count": 1,
    }
    assert json.loads((attempt / result["analysis"]).read_text()) == {
        "schema": "ecos.replay.analysis.v2",
        "views": [],
        "unavailable": [],
        "geometry_display": True,
    }


def test_begin_uses_filesystem_clock_and_invalidates_drc_binding(tmp_path, monkeypatch):
    step = step_at(tmp_path)
    manifest = Path(step.output.geometry_manifest)
    manifest.write_text(manifest.read_text() + "drc=old.gdisplay\n")
    original = Path.touch

    def touch_with_server_clock(path, *args, **kwargs):
        original(path, *args, **kwargs)
        os.utime(path, ns=(123456, 123456))

    monkeypatch.setattr(Path, "touch", touch_with_server_clock)
    assert begin(step) == 123456
    assert "drc=" not in manifest.read_text()
    assert list((tmp_path / "data").iterdir()) == []


def test_helper_rcx_assets_are_not_published_or_replayed_as_filler_results(tmp_path):
    from chipcompiler.tools.replay_analysis import collect_analysis

    step = step_at(tmp_path)
    source = tmp_path / "data/clock_tree/rcx/result.gdisplay"
    asset(source, key="rcx:typical", kind="rcx", records=True)
    step.name = "filler"
    publish(step, 0)
    assert published(step) == []
    assert collect_analysis(step, tmp_path / "attempt-filler", 0) == {}
    # The owning RCX stage still publishes and reuses exactly the same data.
    step.name = "RCX"
    publish(step, 0)
    assert [metadata(path)["kind"] for path in published(step)] == ["rcx"]
    assert collect_analysis(step, tmp_path / "attempt-rcx", 0) == {
        "analysis": "subflows/analysis/overlays/index.json",
        "analysis_view_count": 1,
    }
    # An already-bound auxiliary dataset must not leak into a new Replay index.
    step.name = "filler"
    assert collect_analysis(step, tmp_path / "attempt-existing", 0) == {}
