"""The ledger round trip is the persisted-format contract for the step enums.

`flow.json` is the only ledger format; writing and reading it must not change
any step, tool, state or category value when the members are `StrEnum`.
"""

import copy
import json

from chipcompiler.data import OriginDesign, Workspace
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.rtl2gds import build_flow_range


def test_flow_ledger_round_trip_preserves_every_value(tmp_path):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd", top_module="gcd"))
    flow_path = tmp_path / "home" / "flow.json"
    flow_path.parent.mkdir(parents=True)
    workspace.flow.path = flow_path
    flow = EngineFlow(workspace)
    flow.workspace.flow.data = {
        "steps": [
            flow.init_flow_step(step, tool, state)
            for step, tool, state in build_flow_range("Synthesis", "Harden")
        ]
    }
    before_steps = copy.deepcopy(flow.workspace.flow.data["steps"])

    assert flow.save()

    on_disk = json.loads(flow_path.read_text(encoding="utf-8"))
    reloaded = EngineFlow(workspace)
    assert on_disk["steps"] == before_steps
    assert reloaded.workspace.flow.data["steps"] == before_steps
    for step in reloaded.workspace.flow.data["steps"]:
        for key in ("name", "tool", "state", "category"):
            assert type(step[key]) is str
