import json
import os
from types import SimpleNamespace

from chipcompiler.data import EccOutput, EccStep
from chipcompiler.tools.replay_analysis import collect_analysis


def test_drc_results_freeze_native_positions_and_do_not_reuse_old_report(tmp_path):
    step = SimpleNamespace(name="drc", directory=tmp_path / "drc_ecc")
    report = step.directory / "data/drc/violation_map.json"
    report.parent.mkdir(parents=True)
    row = {"type": "cut_spacing", "shape": [1, 2, 3, 4, "M2"], "original_layer": "V1", "net": ["n"]}
    report.write_text(json.dumps([row]))
    attempt = tmp_path / "attempt"
    result = collect_analysis(step, attempt, 0)
    payload = json.loads((attempt / result["analysis"]).read_text())
    view = payload["views"][0]
    assert view["items"] == [
        {
            "label": "cut_spacing",
            "details": {"original_layer": "V1"},
            "bboxes": [[1, 2, 3, 4]],
            "nets": ["n"],
        }
    ]
    report.write_text("[]")
    assert json.loads((attempt / result["analysis"]).read_text())["views"][0] == view
    assert view["source"]["report"] == "data/drc/violation_map.json"
    assert not (attempt / "subflows/analysis/overlays/sources").exists()
    os.utime(report, ns=(1, 1))
    result = collect_analysis(step, tmp_path / "new", 2)
    assert result["analysis_view_count"] == 0
    assert json.loads((tmp_path / "new" / result["analysis"]).read_text())["unavailable"]


def test_timing_retains_corner_slack_and_pin_path_without_guessing_geometry(tmp_path):
    step = SimpleNamespace(name="sta", directory=tmp_path / "sta_ecc")
    report = step.directory / "feature/slow/rc/timing_paths.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps(
            {
                "corner": "slow",
                "paths": [
                    {
                        "analysis_type": "setup",
                        "slack_ns": -0.2,
                        "start_point": "a/Q",
                        "end_point": "b/D",
                        "stages": [
                            {"instance": "a", "pin": "a/Q"},
                            {"instance": "b", "pin": "b/D"},
                        ],
                    }
                ],
            }
        )
    )
    result = collect_analysis(step, tmp_path / "attempt", 0)
    view = json.loads((tmp_path / "attempt" / result["analysis"]).read_text())["views"][0]
    assert view["label"] == "slow · setup"
    assert view["items"][0]["details"]["stages"] == [
        {"instance": "a", "pin": "a/Q"},
        {"instance": "b", "pin": "b/D"},
    ]
    assert view["items"][0]["value"] == -0.2
    assert "bboxes" not in view["items"][0]


def test_sizer_output_cleanup_preserves_live_replay(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_sizer import runner

    geometry = tmp_path / "geometry"
    capture = geometry / "replay/attempts/live/capture"
    capture.mkdir(parents=True)
    (geometry / "replay/manifest.json").write_text('{"status":"recording"}')
    (geometry / "old_shapes.bin").write_bytes(b"stale")
    step = EccStep(name="timingOpt", tool="sizer", output=EccOutput(geometry=geometry))
    monkeypatch.setattr(runner, "_published_paths", lambda _: [geometry])
    runner._delete_published_outputs(step)
    assert capture.is_dir()
    assert list(geometry.iterdir()) == [geometry / "replay"]


def test_power_components_keep_watts_and_reported_totals(tmp_path):
    from chipcompiler.tools.replay_analysis import power

    path = tmp_path / "instance_power.tsv"
    path.write_text(
        "instance_name\tinternal_power_w\tswitching_power_w\tleakage_power_w\ttotal_power_w\n"
        "a\t0.1\t0.2\t0.01\t0.31\n"
        "b\t0.2\t0.4\t0.02\t0.62\n"
    )
    views = power(path)
    assert [(v["summary"]["component"], v["unit"]) for v in views] == [
        (component, "W") for component in ["total", "internal", "switching", "leakage"]
    ]
    assert [v["items"][0]["value"] for v in views] == [0.31, 0.1, 0.2, 0.01]
    assert all(v["summary"]["reported_sum_w"] == sum(i["value"] for i in v["items"]) for v in views)


def test_formal_witness_stays_logical_and_is_frozen_before_staging_cleanup(tmp_path):
    step = SimpleNamespace(name="lec", directory=tmp_path / "lec")
    directory = tmp_path / "attempt"
    capture = directory / "capture"
    capture.mkdir(parents=True)
    witness = {
        "bad_frame": 2,
        "output_mismatches": [{"signal": "y", "golden": True, "revised": False}],
    }
    event = capture / "kepler-worker-0.json"
    event.write_text(
        json.dumps(
            {"phase": "sec_counterexample", "state_domain": "analysis_state", "metrics": witness}
        )
    )
    result = collect_analysis(step, directory, 0)
    event.unlink()
    view = json.loads((directory / result["analysis"]).read_text())["views"][0]
    assert view["summary"]["coordinate_space"] == "logical"
    assert view["items"] == [
        {"label": key.replace("_", " "), "details": value} for key, value in witness.items()
    ]
    assert not any("instances" in item or "bboxes" in item for item in view["items"])


def test_power_geometry_is_preferred_frozen_and_stale_or_invalid_geometry_falls_back(tmp_path):
    step = SimpleNamespace(name="power_analysis", directory=tmp_path / "powerAnalysis_ecc")
    raw = step.directory / "data/pw/power_reporter/instance_power.tsv"
    spatial = step.directory / "output/geometry/power/instance_power_geometry.tsv"
    raw.parent.mkdir(parents=True)
    spatial.parent.mkdir(parents=True)
    raw.write_text("instance_name\ttotal_power_w\na\t0.31\n")
    spatial.write_text("instance_name\tlx\tly\thx\thy\ttotal_power_w\na\t1\t2\t3\t4\t0.31\n")
    metadata = {
        "schema": "ecos.power.geometry.v1",
        "matched_instances": 1,
        "unresolved_instances": 2,
    }
    spatial.with_name("metadata.json").write_text(json.dumps(metadata))
    attempt = tmp_path / "a"
    result = collect_analysis(step, attempt, 2)
    (view,) = json.loads((attempt / result["analysis"]).read_text())["views"]
    assert view["items"] == [{"instance_ref": 0, "value": 0.31}]
    assert json.loads((attempt / result["analysis"]).read_text())["instances"] == ["a"]
    assert view["summary"]["spatial_coverage"] == metadata
    source = attempt / result["analysis"]
    frozen = source.read_text()
    os.utime(spatial, ns=(1, 1))
    result = collect_analysis(step, tmp_path / "b", 2)
    (fallback,) = json.loads((tmp_path / "b" / result["analysis"]).read_text())["views"]
    assert fallback["items"] == [{"instance_ref": 0, "value": 0.31}]
    spatial.write_text("instance_name\tlx\tly\thx\thy\ttotal_power_w\na\t3\t2\t1\t4\t0.31\n")
    result = collect_analysis(step, tmp_path / "c", 2)
    (fallback,) = json.loads((tmp_path / "c" / result["analysis"]).read_text())["views"]
    assert fallback["items"] == [{"instance_ref": 0, "value": 0.31}]
    assert source.read_text() == frozen
