"""Pins the signoff-package analysis projection before the input rule is unified.

``_refresh_workspace_analysis`` feeds each step from the previous non-LEC,
non-advisory step; it does not consult ``category`` or ``input_step``. The
execution chain and the read-only projections are pinned separately and are
allowed to disagree on this ledger.
"""

from typing import Any

from chipcompiler.data import OriginDesign, StateEnum, StepEnum, Workspace
from chipcompiler.data.workspace.flow_data import build_dynamic_flow_data
from chipcompiler.engine.signoff.analysis import CollectorAnalysisMixin
from chipcompiler.tools.ecc.builder import build_step as build_ecc_step


class _RecordingCollector(CollectorAnalysisMixin):
    def __init__(self, workspace):
        self.workspace = workspace
        self.refreshed = []
        self.issues = []

    def _refresh_step_analysis(self, step) -> None:
        self.refreshed.append(step)

    def _analysis_issue(
        self,
        step_name: str,
        *,
        required: bool,
        reason: str,
        kind: str,
        label: str | None = None,
    ) -> Any:
        self.issues.append((step_name, kind, reason))
        return None


def _source_name(workspace, input_def, output_paths) -> str:
    if input_def == workspace.design.origin_def:
        return "origin"
    for name, path in output_paths.items():
        if input_def == path:
            return name
    return f"unknown:{input_def}"


def test_refresh_workspace_analysis_chains_the_previous_step(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(
            name="gcd",
            top_module="gcd",
            origin_def=tmp_path / "origin.def",
            origin_verilog=tmp_path / "origin.v",
        ),
    )
    ledger = build_dynamic_flow_data({"start_step": "route", "end_step": "Harden"})
    for step in ledger.get("steps", []):
        step["state"] = StateEnum.Success.value
    workspace.flow.data = ledger
    workspace.flow.path = tmp_path / "flow.json"
    collector = _RecordingCollector(workspace)

    collector._refresh_workspace_analysis(tmp_path)

    assert collector.issues == []
    output_paths = {
        name.value: build_ecc_step(workspace, name.value, None, None).output.def_
        for name in (
            StepEnum.ROUTING,
            StepEnum.FILLER,
            StepEnum.LVS,
            StepEnum.DRC,
            StepEnum.ANTENNA_CHECK,
            StepEnum.RCX,
            StepEnum.STA,
            StepEnum.POWER_ANALYSIS,
            StepEnum.EMIR,
            StepEnum.HARDEN,
        )
    }
    sources = {
        step.name: _source_name(workspace, step.input.def_, output_paths)
        for step in collector.refreshed
    }

    # postRouteLec is skipped by the LEC branch and is never refreshed.
    assert sources == {
        "route": "origin",
        "filler": "route",
        "lvs": "filler",
        "drc": "filler",
        "antennaCheck": "filler",
        "RCX": "filler",
        "sta": "filler",
        "powerAnalysis": "filler",
        "emir": "filler",
        "Harden": "filler",
    }


def test_invalid_explicit_input_is_reported_as_an_issue(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(
            name="gcd",
            top_module="gcd",
            origin_def=tmp_path / "origin.def",
            origin_verilog=tmp_path / "origin.v",
        ),
    )
    ledger = build_dynamic_flow_data({"start_step": "route", "end_step": "Harden"})
    for step in ledger.get("steps", []):
        step["state"] = StateEnum.Success.value
    next(step for step in ledger.get("steps", []) if step["name"] == "RCX")["input_step"] = (
        "does_not_exist"
    )
    workspace.flow.data = ledger
    workspace.flow.path = tmp_path / "flow.json"
    collector = _RecordingCollector(workspace)

    collector._refresh_workspace_analysis(tmp_path)

    assert any(
        step_name == "RCX" and "Could not construct" in reason
        for step_name, _kind, reason in collector.issues
    )
