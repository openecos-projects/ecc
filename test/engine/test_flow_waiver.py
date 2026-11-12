from types import SimpleNamespace

import pytest

from chipcompiler.data import Workspace
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.engine.flow_waiver import mark_step_skipped, waive_checklist
from chipcompiler.engine.rerun import invalidate_from
from chipcompiler.engine.workspace_reset import prepare_steps_for_rerun


class _Flow:
    def __init__(self, steps):
        self._steps = steps
        self.saves = 0

    def steps(self):
        return self._steps

    def save(self):
        self.saves += 1
        return True


class _Workspace:
    def __init__(self, steps):
        self.flow = _Flow(steps)


def test_mark_step_skipped_records_reason_and_clears_checklist_gate():
    step = {
        "name": "postRouteLec",
        "tool": "kepler_formal",
        "category": "CHECKER",
        "state": "Incomplete",
        "checklist_status": {
            "status": "blocked",
            "blocked": True,
            "failed_items": ["artifact.postroutelec.result"],
        },
    }
    workspace = _Workspace([step])

    mark_step_skipped(workspace, "postRouteLec", "formal difference in input netlist")

    assert step["state"] == "Skipped"
    assert step["skip_reason"] == "formal difference in input netlist"
    assert step["checklist_status"]["status"] == "skipped"
    assert step["checklist_status"]["blocked"] is False
    assert workspace.flow.saves == 1


def test_mark_step_skipped_rejects_non_skippable_step():
    workspace = _Workspace([{"name": "filler", "tool": "ecc", "category": "PNR"}])

    with pytest.raises(ValueError, match="not skippable"):
        mark_step_skipped(workspace, "filler", "not applicable")


def test_waive_checklist_records_reason_without_touching_blocked_status():
    step = {
        "name": "sta",
        "tool": "ecc",
        "category": "CHECKER",
        "state": "Success",
        "checklist_status": {"status": "blocked", "blocked": True},
    }
    workspace = _Workspace([step])

    waive_checklist(workspace, "sta", "timing violations accepted for flow completion")

    assert step["checklist_status"]["status"] == "blocked"
    assert step["checklist_waiver"]["reason"] == "timing violations accepted for flow completion"
    assert workspace.flow.saves == 1


def test_waive_checklist_rejects_pnr_step():
    workspace = _Workspace([{"name": "Harden", "tool": "ecc", "category": "PNR"}])

    with pytest.raises(ValueError, match="only checker steps"):
        waive_checklist(workspace, "Harden", "not applicable")


def _waived_workspace(tmp_path):
    workspace = Workspace(directory=tmp_path)
    flow = EngineFlow(workspace)
    flow_path = tmp_path / "home" / "flow.json"
    flow_path.parent.mkdir()
    workspace.flow.path = flow_path
    workspace.flow.data = {
        "steps": [
            {
                "name": "sta",
                "tool": "ecc",
                "category": "CHECKER",
                "state": "Success",
                "checklist_status": {"status": "blocked", "blocked": True},
            }
        ]
    }
    waive_checklist(workspace, "sta", "accepted result")
    return workspace, flow


def test_rerun_invalidation_clears_checklist_waiver(tmp_path):
    workspace, flow = _waived_workspace(tmp_path)

    invalidate_from(flow, "sta")

    assert "checklist_waiver" not in workspace.flow.steps()[0]


def test_derived_workspace_reset_clears_checklist_waiver(tmp_path):
    workspace, flow = _waived_workspace(tmp_path)
    step = SimpleNamespace(name="sta", tool="ecc")

    prepare_steps_for_rerun(workspace, flow, [step])

    assert "checklist_waiver" not in workspace.flow.steps()[0]


def test_full_flow_reset_clears_checklist_waiver(tmp_path):
    workspace, flow = _waived_workspace(tmp_path)

    flow.clear_states()

    assert "checklist_waiver" not in workspace.flow.steps()[0]
