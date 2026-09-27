import json
from pathlib import Path

from chipcompiler.engine.interrupted_run import recover_interrupted_run


def _flow(tmp_path: Path, info: dict | None) -> Path:
    workspace = tmp_path / "workspace"
    home = workspace / "home"
    home.mkdir(parents=True)
    (home / "flow.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "steps": [
                    {
                        "name": "Synthesis",
                        "tool": "yosys",
                        "state": "Ongoing",
                        "info": info or {},
                    }
                ],
            }
        )
    )
    return workspace


def test_recovers_matching_transport_neutral_marker(tmp_path):
    workspace = _flow(
        tmp_path,
        {"execution": {"schema_version": 1, "run_id": "run-1", "started_at": 1.0}},
    )
    assert recover_interrupted_run(
        workspace, run_id="run-1", allow_markerless=False
    ) == ("Synthesis",)
    step = json.loads((workspace / "home" / "flow.json").read_text())["steps"][0]
    assert step["state"] == "Incomplete"
    assert "execution" not in step["info"]


def test_registered_recovery_does_not_touch_another_run(tmp_path):
    workspace = _flow(
        tmp_path,
        {"execution": {"schema_version": 1, "run_id": "run-2", "started_at": 1.0}},
    )
    assert recover_interrupted_run(workspace, run_id="run-1", allow_markerless=False) == ()
    step = json.loads((workspace / "home" / "flow.json").read_text())["steps"][0]
    assert step["state"] == "Ongoing"


def test_orphan_recovery_accepts_legacy_markerless_flow(tmp_path):
    workspace = _flow(tmp_path, None)
    assert recover_interrupted_run(
        workspace, run_id=None, allow_markerless=True
    ) == ("Synthesis",)
