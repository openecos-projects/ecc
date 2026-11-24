"""Terminal placement keeps its flow boundary and captures the saved database."""

import json
from types import SimpleNamespace

from chipcompiler.data import EccStep, Workspace
from chipcompiler.tools import replay
from chipcompiler.tools.ecc import metrics, runner


def test_terminal_capture_reloads_committed_geometry_without_routing(monkeypatch, tmp_path):
    capture = tmp_path / "capture"
    capture.mkdir()
    monkeypatch.setenv("ECC_REPLAY_CAPTURE_DIR", str(capture))
    monkeypatch.setenv("ECC_REPLAY_START_NS", "0")
    step = EccStep(name="placement", tool="dreamplace")
    step.output.def_ = tmp_path / "placed.def"
    step.output.verilog = tmp_path / "placed.v"
    step.feature.db = tmp_path / "place.db.json"
    workspace = Workspace(directory=tmp_path)
    calls = []
    objects = {"inst:a": {"kind": "instance", "bbox": [20, 0, 30, 10]}}
    committed = SimpleNamespace(
        ecc=SimpleNamespace(replay_geometry=lambda: json.dumps(objects)),
        feature_sammry=lambda **kw: calls.append(("summary", kw["json_path"])),
        close=lambda: calls.append("close committed"),
    )
    original = SimpleNamespace(close=lambda: calls.append("close input"))

    def load(ws, saved):
        assert ws is workspace
        assert saved.input.def_ == step.output.def_
        assert saved.input.verilog == step.output.verilog
        calls.append("load committed")
        return committed

    monkeypatch.setattr(runner, "create_db_engine", load)
    monkeypatch.setattr(metrics, "build_metrics_db", lambda _w, _s: {"Instance number": 1})
    monkeypatch.setattr(
        metrics,
        "save_qor_metrics",
        lambda _w, _s, value: calls.append(("metrics", value.data)) or True,
    )
    replay.capture_placement_result(workspace, step, original)
    frame = json.loads((capture / "native-final.json").read_text())
    assert (frame["phase"], frame["state_domain"], frame["objects"]) == (
        "committed_database",
        "native_committed",
        objects,
    )
    assert calls == [
        "close input",
        "load committed",
        ("summary", step.feature.db),
        ("metrics", {"Instance number": 1}),
        "close committed",
    ]


def test_disabled_terminal_capture_never_touches_native_database(monkeypatch):
    monkeypatch.delenv("ECC_REPLAY_CAPTURE_DIR", raising=False)
    replay.capture_placement_result(None, None, None)


def test_missing_committed_database_marks_replay_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("ECC_REPLAY_CAPTURE_DIR", str(tmp_path))
    monkeypatch.setattr(runner, "create_db_engine", lambda *_: None)
    replay.capture_placement_result(Workspace(directory=tmp_path), EccStep(name="placement"), None)
    assert json.loads((tmp_path / "error.json").read_text()) == {
        "error": "Cannot load committed placement for Replay"
    }
