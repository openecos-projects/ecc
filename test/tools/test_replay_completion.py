import json
import os
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.tools.replay import capture_step, capture_subflow
from chipcompiler.tools.replay_artifacts import reference_geometry
from chipcompiler.tools.replay_completion import finalize, prepare
from chipcompiler.tools.replay_integrity import fingerprint
from chipcompiler.tools.replay_metrics import attach_comparisons


def setup(tmp_path):
    workspace = SimpleNamespace(
        directory=tmp_path, parameters=SimpleNamespace(data={"replay": {"enabled": True}})
    )
    step = SimpleNamespace(
        name="synthesis",
        tool="yosys",
        directory=tmp_path / "Synthesis_yosys",
        output=SimpleNamespace(),
        checklist=SimpleNamespace(path=tmp_path / "checklist.json"),
    )
    return workspace, step


def test_parent_freezes_checklist_after_tool_returns_and_never_overwrites_new_attempt(tmp_path):
    workspace, step = setup(tmp_path)
    attempt = prepare(workspace, step)
    with capture_step(workspace, step, attempt_id=attempt) as outcome:
        capture_subflow("run yosys", "Success")
        outcome["ok"] = True
    root = step.directory / "output/geometry/replay"
    assert json.loads((root / "manifest.json").read_text())["status"] == "sealed"
    checklist = {"status": "blocked", "checklist": [{"title": "Check", "blocked": True}]}
    step.checklist.path.write_text(json.dumps(checklist))
    finalize(workspace, step, attempt, "Success", checklist_current=True)
    manifest_path = root / f"attempts/{attempt}/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["result_checklist"] == checklist
    step.checklist.path.write_text('{"status":"ready","checklist":[]}')
    assert json.loads(manifest_path.read_text())["result_checklist"] == checklist
    newer = prepare(workspace, step)
    finalize(workspace, step, attempt, "Imcomplete")
    assert json.loads((root / "manifest.json").read_text())["attempt_id"] == newer


def test_parent_failure_cannot_publish_tool_success(tmp_path):
    workspace, step = setup(tmp_path)
    attempt = prepare(workspace, step)
    with capture_step(workspace, step, attempt_id=attempt) as outcome:
        capture_subflow("run yosys", "Success")
        outcome["ok"] = True
    finalize(workspace, step, attempt, "Imcomplete")
    pointer = json.loads((step.directory / "output/geometry/replay/manifest.json").read_text())
    assert pointer["status"] == "unavailable"


def test_geometry_reference_owns_content_identity_without_copying_side_files(tmp_path):
    source = tmp_path / "geometry"
    source.mkdir()
    (source / "nodes.bin").write_bytes(b"original")
    manifest = source / "geometry.manifest"
    manifest.write_text("schema_version=1\nclock_tree_meta=nodes.bin\nclock_tree_nodes=nodes.bin\n")
    result = reference_geometry(manifest)
    expected = {
        "manifest": "geometry.manifest",
        "clock_tree": True,
        "files": {
            "geometry.manifest": fingerprint(manifest),
            "nodes.bin": fingerprint(source / "nodes.bin"),
        },
    }
    assert result == {"shared_geometry": expected}
    (source / "nodes.bin").write_bytes(b"changed")
    assert fingerprint(source / "nodes.bin") != expected["files"]["nodes.bin"]
    assert sorted(p.name for p in source.iterdir()) == ["geometry.manifest", "nodes.bin"]


def test_missing_fresh_checklist_does_not_reuse_previous_success(tmp_path):
    workspace, step = setup(tmp_path)
    step.checklist.path.write_text('{"status":"ready","checklist":[]}')
    os.utime(step.checklist.path, ns=(1, 1))
    with capture_step(workspace, step) as outcome:
        capture_subflow("run yosys", "Success")
        outcome["ok"] = True
    root = step.directory / "output/geometry/replay"
    pointer = json.loads((root / "manifest.json").read_text())
    manifest = json.loads((root / pointer["manifest"]).read_text())
    assert manifest["result_checklist"]["status"] == "unavailable"


def test_only_explicit_compatible_baseline_is_compared():
    old = {
        "id": "instance_count",
        "value": 2,
        "unit": "count",
        "source": {"selector": "/Instances/all/num"},
    }
    timing = {"id": "wns", "value": -1, "unit": "ns", "corner": "slow"}
    baseline = {"source_step": "actual_input", "input_sha256": "a" * 64, "metrics": [old, timing]}
    values = [{**old, "value": 3}, {**timing, "value": 1, "corner": "fast"}]
    compared = attach_comparisons(values, baseline)
    assert compared[0]["comparison"]["delta"] == 1
    assert compared[1] == values[1]
    assert attach_comparisons(values, None) == values


def test_failed_check_exposes_current_diagnostics_without_success_semantics(tmp_path):
    from chipcompiler.tools.replay_storage import atomic_json

    workspace, step = setup(tmp_path)
    step.name, step.tool = "drc", "ecc"
    attempt = prepare(workspace, step)
    with capture_step(workspace, step, attempt_id=attempt):
        atomic_json(
            step.directory / "data/drc/violation_map.json",
            [{"type": "short", "shape": [10, 20, 30, 40], "net": ["a", "b"]}],
        )
        atomic_json(
            Path(os.environ["ECC_REPLAY_CAPTURE_DIR"]) / "input.json",
            {
                "sequence": 0,
                "elapsed_ns": 0,
                "phase": "input_database",
                "subflow": "load data",
                "state_domain": "native_input",
                "objects": {"die": {"kind": "die", "bbox": [0, 0, 100, 100]}},
            },
        )
    step.checklist.path.write_text('{"status":"blocked","checklist":[]}')
    finalize(workspace, step, attempt, "Incomplete", checklist_current=True)
    root = step.directory / "output/geometry/replay"
    pointer = json.loads((root / "manifest.json").read_text())
    manifest = json.loads((root / pointer["manifest"]).read_text())
    assert pointer["status"] == manifest["status"] == "diagnostic_only"
    assert manifest["flow_state"] == "Incomplete"
    assert manifest["frames"][-1]["state_domain"] == "analysis_complete"
    assert manifest["result_checklist"]["status"] == "blocked"
    assert manifest["analysis_view_count"] == 1
