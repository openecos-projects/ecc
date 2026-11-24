"""Replay lifecycle and producer contract, independent of installed EDA binaries."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.tools.replay import atomic_json, capture_step, publish, read_settings


def sample(directory, sequence, objects, *, scope=None, final=False):
    atomic_json(
        directory / f"{sequence}.json",
        {
            "sequence": sequence,
            "elapsed_ns": sequence * 100,
            "phase": "writeback" if final else "iteration",
            "subflow": "place",
            "state_domain": "native_committed" if final else "algorithm_state",
            "scope": scope,
            "objects": objects,
        },
    )


def instance(x):
    return {"kind": "instance", "bbox": [x, 0, x + 10, 10]}


def test_diffs_preserve_input_pdn_and_checkpoint_touched_state(tmp_path):
    capture = tmp_path / "attempts/a/capture"
    baseline = {"inst:a": instance(0), "pg:p": {"kind": "pdn", "bbox": [0, 0, 5, 90]}}
    sample(capture, 0, baseline)
    sample(capture, 1, {"inst:a": instance(20), "inst:b": instance(40)}, scope="instances")
    sample(capture, 2, {"inst:a": instance(0)}, scope="instances", final=True)
    publish(tmp_path, "a", "placement", "dreamplace", 300)
    manifest = json.loads((tmp_path / "attempts/a/manifest.json").read_text())
    frames = [
        json.loads((tmp_path / "attempts/a" / f["path"]).read_text()) for f in manifest["frames"]
    ]
    assert frames[0]["touched"] == []
    assert frames[1]["upsert"] == {"inst:b": instance(40)}
    assert frames[1]["translate"] == {"inst:a": [20, 0]}
    assert manifest["schema"] == "ecos.replay.v2"
    assert frames[-1]["base_checkpoint"] == 0
    assert frames[-1]["upsert"] == {}
    assert frames[-1]["remove"] == []
    assert manifest["frames"][-1]["encoding"] == "json+base"
    assert frames[0]["upsert"] == baseline
    assert frames[-1]["touched"] == ["inst:a", "inst:b"]
    assert not capture.exists()


def test_macro_scope_does_not_delete_standard_cells(tmp_path):
    capture = tmp_path / "attempts/a/capture"
    sample(capture, 0, {"inst:a": instance(0), "inst:m": {"kind": "macro", "bbox": [0, 0, 50, 50]}})
    sample(
        capture,
        1,
        {"inst:m": {"kind": "macro", "bbox": [20, 0, 70, 50]}},
        scope="macros",
        final=True,
    )
    publish(tmp_path, "a", "macro_placement", "dreamplace", 100)
    end = json.loads((tmp_path / "attempts/a/subflows/000/frames/000001.json").read_text())
    assert end["upsert"]["inst:a"] == instance(0)
    assert end["touched"] == ["inst:m"]


@pytest.fixture
def execution(tmp_path):
    workspace = SimpleNamespace(directory=tmp_path, parameters=SimpleNamespace(data={}))
    step = SimpleNamespace(
        name="placement",
        tool="dreamplace",
        output=SimpleNamespace(geometry=tmp_path / "place_dreamplace/output/geometry"),
    )
    return workspace, step


def test_default_off_and_disabled_rerun_invalidates_old_attempt(execution, monkeypatch):
    workspace, step = execution
    root = step.output.geometry / "replay"
    atomic_json(root / "manifest.json", {"status": "complete", "attempt_id": "old"})
    monkeypatch.setenv("ECC_REPLAY_CAPTURE_DIR", "/inherited")
    with capture_step(workspace, step) as outcome:
        assert "ECC_REPLAY_CAPTURE_DIR" not in os.environ
        outcome["ok"] = True
    assert json.loads((root / "manifest.json").read_text())["status"] == "stale"
    assert os.environ["ECC_REPLAY_CAPTURE_DIR"] == "/inherited"
    assert not (root / "attempts").exists()


@pytest.mark.parametrize("failed", [False, True])
def test_success_and_failure_publish_different_terminal_states(execution, failed):
    workspace, step = execution
    workspace.parameters.data["replay"] = {"enabled": True}
    with capture_step(workspace, step) as outcome:
        sample(Path(os.environ["ECC_REPLAY_CAPTURE_DIR"]), 0, {"inst:a": instance(0)}, final=True)
        outcome["ok"] = not failed
    pointer = json.loads((step.output.geometry / "replay/manifest.json").read_text())
    assert pointer["status"] == ("unavailable" if failed else "complete")


def test_missing_final_and_failed_sampler_never_publish(tmp_path):
    capture = tmp_path / "attempts/a/capture"
    sample(capture, 0, {"inst:a": instance(0)})
    with pytest.raises(ValueError, match="committed"):
        publish(tmp_path, "a", "placement", "dreamplace", 10)
    atomic_json(capture / "error.json", {"error": "disk full"})
    with pytest.raises(ValueError, match="capture failed"):
        publish(tmp_path, "a", "placement", "dreamplace", 10)
    assert not (tmp_path / "manifest.json").exists()


def test_settings_reject_truthy_string(execution):
    workspace, _ = execution
    assert read_settings(workspace) is False
    workspace.parameters.data["replay"] = {"enabled": "false"}
    with pytest.raises(ValueError, match="boolean"):
        read_settings(workspace)


def test_all_standard_flow_steps_are_supported_for_replay():
    from chipcompiler.rtl2gds.builder import rtl2gds_step_names
    from chipcompiler.tools.replay import SUPPORTED

    assert set(rtl2gds_step_names()) <= SUPPORTED


def test_report_only_steps_publish_real_subflow_timeline(tmp_path):
    capture = tmp_path / "attempts/a/capture"
    capture.mkdir(parents=True)
    (capture / "subflows.jsonl").write_text(
        '{"name":"run yosys","state":"Success","elapsed_ns":100}\n'
        '{"name":"analysis","state":"Success","elapsed_ns":200}\n'
    )
    publish(tmp_path, "a", "synthesis", "yosys", 200)
    manifest = json.loads((tmp_path / "attempts/a/manifest.json").read_text())
    assert manifest["geometry_detail"] == "report_only"
    assert [frame["subflow"] for frame in manifest["frames"]] == ["run yosys", "analysis"]
    assert [frame["state_domain"] for frame in manifest["frames"]] == [
        "analysis_state",
        "analysis_complete",
    ]


def test_report_only_step_without_geometry_path_still_publishes(tmp_path):
    workspace = SimpleNamespace(
        directory=tmp_path,
        parameters=SimpleNamespace(data={"replay": {"enabled": True}}),
    )
    step_dir = tmp_path / "Synthesis_yosys"
    step = SimpleNamespace(
        name="synthesis",
        tool="yosys",
        directory=step_dir,
        output=SimpleNamespace(dir=step_dir / "output"),
    )
    with capture_step(workspace, step) as outcome:
        from chipcompiler.tools.replay import capture_subflow

        capture_subflow("run yosys", "Success")
        outcome["ok"] = True
    replay_root = step_dir / "output/geometry/replay"
    pointer = json.loads((replay_root / "manifest.json").read_text())
    manifest = json.loads((replay_root / pointer["manifest"]).read_text())
    assert manifest["geometry_detail"] == "report_only"


def test_partial_samples_preserve_master_and_orientation(tmp_path):
    capture = tmp_path / "attempts/a/capture"
    baseline = {"inst:a": {**instance(0), "master": "BUF_X1", "orient": 1}}
    sample(capture, 0, baseline)
    sample(capture, 1, {"inst:a": instance(0)}, scope="instances")
    sample(capture, 2, {"inst:a": {**instance(0), "master": "BUF_X2", "orient": 1}}, final=True)
    publish(tmp_path, "a", "placement", "dreamplace", 300)
    directory = tmp_path / "attempts/a/subflows/000/frames"
    assert json.loads((directory / "000001.json").read_text())["touched"] == []
    assert json.loads((directory / "000002.json").read_text())["touched"] == ["inst:a"]


def test_completion_artifacts_exclude_stale_metrics_and_maps(tmp_path):
    from chipcompiler.tools.replay_results import collect_results

    feature = tmp_path / "feature"
    category = feature / "density_map"
    category.mkdir(parents=True)
    layout, current, stale = [
        category / name for name in ("layout.csv", "current.csv", "stale.csv")
    ]
    metrics = tmp_path / "qor_metrics.json"
    metrics.write_text(
        '{"metrics": [{"id": "area", "value": 20}, '
        '{"id": "runtime_seconds", "category": "runtime", "value": 99}]}'
    )
    for path in (layout, current, stale):
        path.write_text("1,2,3\n")
    for path in (layout, current, metrics):
        os.utime(path, ns=(200, 200))
    os.utime(stale, ns=(50, 50))
    step = SimpleNamespace(
        name="placement",
        feature=SimpleNamespace(dir=feature),
        analysis=SimpleNamespace(qor_metrics=metrics),
    )
    directory = tmp_path / "attempt"
    result = collect_results(step, directory, 100)
    assert result == {
        "result_metrics": [{"id": "area", "value": 20}],
        "maps": "subflows/run-placement/overlays/maps",
    }
    copied = directory / result["maps"] / "density_map"
    assert sorted(p.name for p in copied.iterdir()) == ["current.csv", "layout.csv"]
    assert collect_results(step, tmp_path / "next-attempt", 300) == {"result_metrics": []}


def test_runner_boundaries_include_stages_without_geometry(tmp_path, monkeypatch):
    from chipcompiler.tools.replay import capture_subflow

    capture = tmp_path / "attempts/a/capture"
    sample(capture, 0, {"inst:a": instance(0)})
    sample(capture, 1, {"inst:a": instance(5)}, final=True)
    monkeypatch.setenv("ECC_REPLAY_CAPTURE_DIR", str(capture))
    monkeypatch.setenv("ECC_REPLAY_START_NS", "100")
    ticks = iter((125, 250, 300))
    monkeypatch.setattr("chipcompiler.tools.replay.time.monotonic_ns", lambda: next(ticks))
    capture_subflow("load data", "Success")
    capture_subflow("run placement", "Success")
    capture_subflow("analysis", "Success")
    publish(tmp_path, "a", "placement", "dreamplace", 300)
    manifest = json.loads((tmp_path / "attempts/a/manifest.json").read_text())
    assert manifest["subflow_timing"] == [
        {"name": "load data", "state": "Success", "start_ns": 0, "end_ns": 25},
        {"name": "run placement", "state": "Success", "start_ns": 25, "end_ns": 150},
        {"name": "analysis", "state": "Success", "start_ns": 150, "end_ns": 200},
    ]
    assert not capture.exists()


def test_floorplan_timing_uses_native_stage_end_not_batched_ledger(tmp_path):
    capture = tmp_path / "attempts/a/capture"
    sample(capture, 0, {"inst:a": instance(0)})
    sample(capture, 1, {"inst:a": instance(1)})
    sample(capture, 2, {"inst:a": instance(2)}, final=True)
    raw = capture / "1.json"
    frame = json.loads(raw.read_text())
    frame["subflow"] = "create tracks"
    atomic_json(raw, frame)
    (capture / "subflows.jsonl").write_text(
        json.dumps({"name": "create tracks", "state": "Success", "elapsed_ns": 180}) + "\n"
    )
    publish(tmp_path, "a", "post_floorplan", "ecc", 300)
    manifest = json.loads((tmp_path / "attempts/a/manifest.json").read_text())
    assert manifest["subflow_timing"] == [
        {"name": "create tracks", "state": "Success", "start_ns": 0, "end_ns": 100}
    ]


def test_subflow_ongoing_and_success_form_one_timed_node(tmp_path):
    capture = tmp_path / "attempts/a/capture"
    sample(capture, 0, {"inst:a": instance(0)})
    sample(capture, 1, {"inst:a": instance(5)}, final=True)
    (capture / "subflows.jsonl").write_text(
        '{"name":"run placement","state":"Ongoing","elapsed_ns":20}\n'
        '{"name":"run placement","state":"Success","elapsed_ns":80}\n'
    )
    publish(tmp_path, "a", "placement", "dreamplace", 100)
    manifest = json.loads((tmp_path / "attempts/a/manifest.json").read_text())
    assert manifest["subflow_timing"] == [
        {"name": "run placement", "state": "Success", "start_ns": 20, "end_ns": 80}
    ]


def test_deleted_name_reuse_gets_a_new_lifetime_and_retains_deletion_marker(tmp_path):
    root = tmp_path / "replay"
    capture = root / "attempts/a/capture"
    capture.mkdir(parents=True)
    for i, objects in enumerate([{"inst:a": instance(0)}, {}, {"inst:a": instance(10)}]):
        sample(capture, i, objects, final=i == 2)
    publish(root, "a", "placement", "ecc", 10**12)
    manifest = json.loads((root / "attempts/a/manifest.json").read_text())
    final = json.loads((root / "attempts/a" / manifest["frames"][-1]["path"]).read_text())
    assert set(final["upsert"]) == {"inst:a#birth:1"}
    assert set(final["deleted"]) == {"inst:a"}
    assert final["restored"] == []


def test_route_replacement_preserves_power_and_pin_vias(tmp_path):
    capture = tmp_path / "attempts/a/capture"
    baseline = {
        "power": {"kind": "via", "net_kind": "power", "bbox": [0, 0, 2, 2]},
        "pin": {"kind": "via", "net_kind": "pin", "bbox": [4, 4, 6, 6]},
        "old": {"kind": "via", "net_kind": "signal", "bbox": [8, 8, 10, 10]},
    }
    routed = {"new": {"kind": "wire", "bbox": [10, 10, 20, 20]}}
    sample(capture, 0, baseline)
    sample(capture, 1, routed, scope="routing", final=True)
    publish(tmp_path, "a", "routing", "ecc", 100)
    final = json.loads((tmp_path / "attempts/a/subflows/000/frames/000001.json").read_text())
    assert final["upsert"] == {"power": baseline["power"], "pin": baseline["pin"], **routed}


def test_v2_compressed_frame_declares_encoding_and_round_trips(tmp_path):
    import gzip

    from chipcompiler.tools.replay_delta import write_frame

    payload = {"large": "captured" * 160000}
    path, encoding = write_frame(tmp_path, "frames/0.json", payload)
    assert encoding == "gzip+json"
    assert json.loads(gzip.decompress((tmp_path / path).read_bytes())) == payload
    assert (tmp_path / path).stat().st_size < 20000
