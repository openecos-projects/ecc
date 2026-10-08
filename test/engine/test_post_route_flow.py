import pytest

from chipcompiler.data import OriginDesign, StepEnum, Workspace
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.rtl2gds import build_flow_range
from chipcompiler.tools.ecc.builder import build_step as build_ecc_step
from chipcompiler.tools.kepler_formal.builder import build_step as build_kepler_step
from chipcompiler.tools.yosys_lec.builder import build_step as build_yosys_lec_step
from chipcompiler.utility import json_write


@pytest.mark.parametrize("lec_engine", ["kepler_formal", "yosys_lec"])
@pytest.mark.parametrize("skip", [(), ("postRouteLec",)])
def test_post_route_flow_preserves_physical_inputs_and_sta_parasitics(
    tmp_path, monkeypatch, lec_engine, skip
):
    import chipcompiler.tools as tools

    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(
            name="gcd",
            top_module="gcd",
            origin_def=tmp_path / "origin.def",
            origin_verilog=tmp_path / "origin.v",
        ),
    )
    workspace.flow.data = {
        "steps": [
            {"name": name.value, "tool": tool, "state": state.value}
            for name, tool, state in build_flow_range(
                "route", "Harden", skip=skip, lec_engine=lec_engine
            )
        ]
    }
    workspace.flow.path = tmp_path / "flow.json"
    json_write(workspace.flow.path, workspace.flow.data)

    def create_step(workspace, step, eda, input_def, input_verilog, input_db=None, **kwargs):
        builders = {
            "ecc": build_ecc_step,
            "kepler_formal": build_kepler_step,
            "yosys_lec": build_yosys_lec_step,
        }
        result = builders[eda](
            workspace=workspace,
            step_name=step,
            input_def=input_def,
            input_verilog=input_verilog,
            input_db=input_db,
        )
        if step == StepEnum.RCX.value:
            result.output.spef = [tmp_path / "gcd.spef"]
        return result

    monkeypatch.setattr(tools, "create_step", create_step)
    flow = EngineFlow(workspace=workspace)
    flow.create_step_workspaces()
    steps = {step.name: step for step in flow.workspace_steps}

    physical_names = ["route", "filler", "lvs", "drc", "RCX", "sta", "powerAnalysis", "Harden"]
    for previous_name, current_name in zip(physical_names[:-1], physical_names[1:], strict=True):
        previous = steps[previous_name]
        current = steps[current_name]
        assert (current.input.def_, current.input.verilog, current.input.db) == (
            previous.output.def_,
            previous.output.verilog,
            previous.output.db,
        )
    assert steps["sta"].output.spef == steps["RCX"].output.spef
    if not skip:
        lec = steps["postRouteLec"]
        assert (lec.input.gate_verilog, lec.input.golden_verilog) == (
            steps["drc"].output.verilog,
            workspace.design.origin_verilog,
        )


def test_loading_existing_workspace_preserves_legacy_post_route_order(tmp_path):
    names = [
        "route",
        "filler",
        "RCX",
        "sta",
        "powerAnalysis",
        "lvs",
        "postRouteLec",
        "drc",
        "Harden",
    ]
    ledger = {
        "steps": [
            {
                "name": name,
                "tool": "kepler_formal" if name == "postRouteLec" else "ecc",
                "state": "Success",
            }
            for name in names
        ]
    }
    workspace = Workspace(directory=tmp_path)
    workspace.flow.path = tmp_path / "flow.json"
    json_write(workspace.flow.path, ledger)

    flow = EngineFlow(workspace=workspace)

    assert flow.workspace.flow.data == ledger
