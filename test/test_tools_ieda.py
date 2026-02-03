#!/usr/bin/env python

import os
import sys

current_dir = os.path.split(os.path.abspath(__file__))[0]
root = current_dir.rsplit("/", 1)[0]
sys.path.append(root)

from benchmark import get_parameters  # noqa: E402
from chipcompiler.data import (  # noqa: E402
    StateEnum,
    StepEnum,
    create_workspace,
    get_pdk,
    log_workspace,
)
from chipcompiler.engine import EngineFlow  # noqa: E402


def test_sky130_gcd():
    workspace_dir = f"{root}/test/examples/sky130_gcd"

    input_def = ""
    # input_verilog = "{}/chipcompiler/thirdparty/ecc-tools/scripts/design/sky130_gcd/result/verilog/gcd.v".format(root)  # verilog file  # noqa: E501
    input_verilog = ""
    input_filelist = f"{root}/test/fixtures/gcd/filelist.f"  # file list
    spef = f"{root}/chipcompiler/thirdparty/ecc-tools/scripts/foundry/sky130/spef/gcd.spef"
    parameters = get_parameters("sky130", "gcd")
    pdk = get_pdk("sky130")
    pdk.spef = spef

    workspace = create_workspace(
        directory=workspace_dir,
        origin_def=input_def,
        origin_verilog=input_verilog,
        pdk=pdk,
        parameters=parameters,
        input_filelist=input_filelist,
    )

    # use the origin def and verilog in workspace for the first step.
    # create eda tool instance
    engine_flow = EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        engine_flow.add_step(step=StepEnum.SYNTHESIS, tool="yosys", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.FLOORPLAN, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.NETLIST_OPT, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.PLACEMENT, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.CTS, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.TIMING_OPT_DRV, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.TIMING_OPT_HOLD, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.LEGALIZATION, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.ROUTING, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.DRC, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.FILLER, tool="ecc", state=StateEnum.Unstart)

    engine_flow.create_step_workspaces()

    log_workspace(workspace=workspace)

    # engine_flow.init_db_engine()
    engine_flow.run_steps()


def test_ics55_gcd():
    workspace_dir = f"{root}/test/examples/ics55_gcd"

    input_def = ""
    input_verilog = f"{root}/test/fixtures/benchmark/dummy/gcd.v"  # RTL file
    spef = f"{root}/chipcompiler/thirdparty/ecc-tools/scripts/foundry/sky130/spef/gcd.spef"
    parameters = get_parameters("ics55", "gcd")
    pdk = get_pdk("ics55")
    pdk.spef = spef

    workspace = create_workspace(
        directory=workspace_dir,
        origin_def=input_def,
        origin_verilog=input_verilog,
        pdk=pdk,
        parameters=parameters,
    )

    engine_flow = EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        engine_flow.add_step(step=StepEnum.SYNTHESIS, tool="yosys", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.FLOORPLAN, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.NETLIST_OPT, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.PLACEMENT, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.CTS, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.LEGALIZATION, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.ROUTING, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.DRC, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.FILLER, tool="ecc", state=StateEnum.Unstart)
    engine_flow.create_step_workspaces()

    log_workspace(workspace=workspace)

    engine_flow.run_steps()


if __name__ == "__main__":
    test_sky130_gcd()

    # test_ics55_gcd()

    exit(0)
