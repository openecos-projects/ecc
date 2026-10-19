import json

from chipcompiler.data import Workspace
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.engine.snapshot import create_engineering_snapshot


def test_flow_save_keeps_snapshot_and_persisted_ledger_identical(tmp_path):
    workspace = Workspace(directory=tmp_path)
    (tmp_path / "home").mkdir()
    workspace.flow.path = tmp_path / "home" / "flow.json"
    flow = EngineFlow(workspace)
    workspace.flow.data = {"steps": [{"name": "Synthesis", "tool": "yosys", "state": "Unstart"}]}
    original_steps = workspace.flow.data["steps"]

    assert flow.save() is True
    snapshot = create_engineering_snapshot(workspace)

    assert snapshot["flow"] == json.loads(workspace.flow.path.read_text())
    assert workspace.flow.data == snapshot["flow"]
    assert workspace.flow.data["steps"] is original_steps
