"""A step rebuilt from its req.json matches the step the flow wired."""

from pathlib import Path

import pytest

from chipcompiler.data import EccOutput, OriginDesign, StepEnum, Workspace
from chipcompiler.data.types import AnalysisData, DesignState
from chipcompiler.data.workspace.flow_data import build_dynamic_flow_data
from chipcompiler.data.workspace.step_handshake import (
    DesignFiles,
    ResponseStatus,
    StepResponse,
    UpstreamResponse,
    write_response,
)
from chipcompiler.engine import step_subprocess
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.engine.step_request import build_step_request


def _wired_flow(tmp_path) -> EngineFlow:
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(
            name="gcd",
            top_module="gcd",
            origin_def=tmp_path / "origin.def",
            origin_verilog=tmp_path / "origin.v",
        ),
    )
    flow = EngineFlow(workspace)
    flow.workspace.flow.data = build_dynamic_flow_data(
        {"start_step": "Synthesis", "end_step": "Harden", "skip_steps": []}
    )
    flow.create_step_workspaces(executable_steps=set(), initialize_config=False)
    return flow


def _request(flow: EngineFlow, name: str):
    step = flow.get_workspace_step(name)
    assert step is not None
    return step, build_step_request(
        Path(flow.workspace.directory),
        flow.workspace.flow.steps(),
        step,
        attempt_id=f"attempt-{name}",
        layout_image=True,
    )


def test_every_step_rebuilds_from_its_request(tmp_path, monkeypatch):
    import chipcompiler.tools as tools

    flow = _wired_flow(tmp_path)
    real_create_step = tools.create_step
    # The parent built optional tools path-only; rebuild them the same way.
    monkeypatch.setattr(
        tools,
        "create_step",
        lambda **kwargs: real_create_step(**kwargs, check_dependency=False),
    )

    for step in flow.workspace_steps:
        wired, request = _request(flow, step.name)
        rebuilt = step_subprocess._build_requested_step(flow.workspace, request)

        assert (rebuilt.directory, rebuilt.input) == (wired.directory, wired.input), step.name
        if isinstance(wired.output, EccOutput) and step.name == StepEnum.STA.value:
            assert isinstance(rebuilt.output, EccOutput)
            assert rebuilt.output.spef == wired.output.spef


def test_sta_accepts_the_filled_design_and_rcx_parasitics(tmp_path):
    flow = _wired_flow(tmp_path)
    write_response(
        tmp_path / "RCX_ecc",
        StepResponse(
            step="RCX",
            tool="ecc",
            attempt_id="attempt-rcx",
            status=ResponseStatus.SUCCESS,
            design=DesignFiles(),
            design_states=frozenset(),
            outputs={AnalysisData.PARASITICS: ()},
            upstream={},
            warnings=frozenset(),
        ),
    )

    _step, request = _request(flow, StepEnum.STA.value)

    assert dict(request.upstream) == {
        DesignState.FILLED: UpstreamResponse("filler_ecc", None),
        DesignState.CLOCK_TREE: UpstreamResponse("filler_ecc", None),
        AnalysisData.PARASITICS: UpstreamResponse("RCX_ecc", "attempt-rcx"),
    }
    assert request.final_step is False


@pytest.mark.parametrize(("name", "final"), [("Harden", True), ("place", False)])
def test_only_the_last_ledger_step_is_final(tmp_path, name, final):
    _step, request = _request(_wired_flow(tmp_path), name)

    assert request.final_step is final


def test_a_step_outside_the_workspace_is_rejected(tmp_path):
    flow = _wired_flow(tmp_path)
    step = flow.get_workspace_step("place")
    assert step is not None
    flow.workspace.directory = tmp_path / "elsewhere"

    with pytest.raises(ValueError, match="not inside the workspace"):
        build_step_request(
            Path(flow.workspace.directory),
            flow.workspace.flow.steps(),
            step,
            attempt_id="attempt",
            layout_image=True,
        )
