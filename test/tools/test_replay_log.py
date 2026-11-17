"""Frozen log bytes must belong to the same attempt and observation clock."""

import json
import time
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.tools.replay_log import LogCapture


def test_append_capture_excludes_old_run_and_has_monotonic_offsets(tmp_path):
    source = tmp_path / "step.log"
    source.write_bytes(b"old run\n")
    attempt = tmp_path / "attempt"
    capture = LogCapture(source, attempt, time.monotonic_ns())
    with source.open("ab") as stream:
        stream.write("[INFO] iteration 30\n温度\n".encode())
    capture.poll()
    with source.open("ab") as stream:
        stream.write(b"[WARN] final\n")
    capture.thread.start()
    assert capture.finish() == {"log_index": "logs/index.json"}
    assert (
        attempt / "logs/step.log"
    ).read_bytes() == "[INFO] iteration 30\n温度\n[WARN] final\n".encode()
    index = json.loads((attempt / "logs/index.json").read_text())
    assert len(index["observations"]) == 2
    first, last = index["observations"]
    assert first["elapsed_ns"] <= last["elapsed_ns"]
    assert first["end_byte"] < last["end_byte"] == (attempt / "logs/step.log").stat().st_size


def test_truncated_source_is_not_mixed_with_prior_bytes(tmp_path):
    source = tmp_path / "step.log"
    source.write_text("previous log")
    capture = LogCapture(source, tmp_path / "attempt", time.monotonic_ns())
    source.write_text("new")
    capture.thread.start()
    assert "log_unavailable" in capture.finish()


def test_missing_and_external_logs_are_optional(tmp_path):
    workspace = SimpleNamespace(directory=tmp_path)
    assert LogCapture.start(workspace, SimpleNamespace(), tmp_path / "a", 0) is None
    step = SimpleNamespace(log=SimpleNamespace(file=tmp_path / "../escape.log"))
    assert LogCapture.start(workspace, step, tmp_path / "a", 0) is None


def test_capture_cap_and_integrity_include_frozen_logs(tmp_path, monkeypatch):
    from chipcompiler.tools import replay_log
    from chipcompiler.tools.replay_integrity import inventory

    monkeypatch.setattr(replay_log, "MAX_BYTES", 6)
    source = tmp_path / "step.log"
    source.touch()
    capture = LogCapture(source, tmp_path / "attempt", time.monotonic_ns())
    source.write_bytes(b"first\nsecond\n")
    capture.thread.start()
    capture.finish()
    index = json.loads((capture.directory / "logs/index.json").read_text())
    assert index["truncated"] is True
    assert capture.target.read_bytes() == b"first\n"
    assert set(inventory(capture.directory)) == {"logs/step.log", "logs/index.json"}


def test_disabled_replay_never_starts_log_observer(tmp_path, monkeypatch):
    from chipcompiler.tools.replay import capture_step

    def unexpected(*args):
        raise AssertionError("Disabled Replay must not observe logs")

    monkeypatch.setattr(LogCapture, "start", unexpected)
    workspace = SimpleNamespace(directory=tmp_path, parameters=SimpleNamespace(data={}))
    step = SimpleNamespace(
        name="place",
        tool="dreamplace",
        output=SimpleNamespace(geometry=tmp_path / "output/geometry"),
        log=SimpleNamespace(file=tmp_path / "log/place.log"),
    )
    with capture_step(workspace, step) as outcome:
        outcome["ok"] = True
    assert not (tmp_path / "output/geometry/replay/attempts").exists()


def test_features_are_frozen_with_source_freshness(tmp_path):
    from chipcompiler.tools.replay_results import collect_results

    feature = tmp_path / "feature"
    feature.mkdir()
    source = feature / "preFloorplan.db.json"
    source.write_text('{"Design Layout":{"die_area":42}}')
    step = SimpleNamespace(name="preFloorplan", tool="ecc", feature=SimpleNamespace(dir=feature))
    attempt = tmp_path / "attempt"
    result = collect_results(step, attempt, source.stat().st_mtime_ns, tmp_path)
    assert result["result_feature_files"] == ["subflows/results/features/db.json"]
    assert (attempt / result["result_feature_files"][0]).read_bytes() == source.read_bytes()
    stale = collect_results(step, tmp_path / "other", source.stat().st_mtime_ns + 1, tmp_path)
    assert stale.get("result_feature_files", []) == []


def test_complete_attempt_publishes_log_index_with_geometry(tmp_path):
    import os

    from chipcompiler.tools.replay import capture_step

    source = tmp_path / "log/place.log"
    source.parent.mkdir()
    source.write_text("previous run\n")
    workspace = SimpleNamespace(
        directory=tmp_path, parameters=SimpleNamespace(data={"replay": {"enabled": True}})
    )
    step = SimpleNamespace(
        name="place",
        tool="dreamplace",
        output=SimpleNamespace(geometry=tmp_path / "output/geometry"),
        log=SimpleNamespace(file=source),
    )
    with capture_step(workspace, step) as outcome:
        with source.open("a") as stream:
            stream.write("[INFO] iteration 30\n[INFO] completed\n")
        sample = {
            "sequence": 0,
            "elapsed_ns": 100,
            "phase": "committed_database",
            "subflow": "save data",
            "state_domain": "native_committed",
            "objects": {},
        }
        (Path(os.environ["ECC_REPLAY_CAPTURE_DIR"]) / "final.json").write_text(json.dumps(sample))
        outcome["ok"] = True
    root = step.output.geometry / "replay"
    pointer = json.loads((root / "manifest.json").read_text())
    manifest = json.loads((root / pointer["manifest"]).read_text())
    attempt = (root / pointer["manifest"]).parent
    assert pointer["status"] == "complete"
    assert manifest["log_index"] == "logs/index.json"
    assert (attempt / "logs/step.log").read_text() == "[INFO] iteration 30\n[INFO] completed\n"
    assert "logs/index.json" in manifest["files"]
