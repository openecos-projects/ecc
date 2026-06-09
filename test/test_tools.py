#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import sys
import os
from pathlib import Path

current_dir = os.path.split(os.path.abspath(__file__))[0]
root = current_dir.rsplit('/', 1)[0]
sys.path.append(root)

from chipcompiler.data import (
    create_workspace,
    load_workspace,
    log_workspace,
    log_parameters,
    StepEnum,
    StateEnum,
    get_pdk,
    get_design_parameters
)

from chipcompiler.engine import (
    EngineDB,
    EngineFlow
)


def _create_minimal_gf180mcu_pdk(root: Path) -> Path:
    tech_path = root / "lef" / "gf180mcu_7t_tech.lef"
    tech_path.parent.mkdir(parents=True, exist_ok=True)
    tech_path.write_text("VERSION 5.8 ;\n")

    lef_path = root / "lef" / "gf180mcu_fd_sc_mcu7t5v0.lef"
    lef_path.write_text("VERSION 5.8 ;\n")

    lib_path = root / "lib" / "gf180mcu_fd_sc_mcu7t5v0__ss_125C_1p65V.lib"
    lib_path.parent.mkdir(parents=True, exist_ok=True)
    lib_path.write_text("library(test) { }\n")

    return root


def _create_minimal_sky130_pdk(root: Path) -> Path:
    tech_path = root / "lef" / "sky130_fd_sc_hd.tech.lef"
    tech_path.parent.mkdir(parents=True, exist_ok=True)
    tech_path.write_text("VERSION 5.8 ;\n")

    lef_path = root / "lef" / "sky130_fd_sc_hd.lef"
    lef_path.write_text("VERSION 5.8 ;\n")

    lib_path = root / "lib" / "sky130_fd_sc_hd__tt_025C_1v80.lib"
    lib_path.parent.mkdir(parents=True, exist_ok=True)
    lib_path.write_text("library(test) { }\n")

    return root


def test_ics55_gcd():
    workspace_dir="{}/test/examples/ics55_gcd_tool".format(root)

    input_def = ""
    input_verilog = "{}/test/fixtures/gcd/gcd.v".format(root) # RTL file
    parameters=get_design_parameters("ics55", "gcd")
    pdk = get_pdk(pdk_name= "ics55")

    workspace = create_workspace(
        directory=workspace_dir,
        origin_def=input_def,
        origin_verilog=input_verilog,
        pdk=pdk,
        parameters=parameters
    )
    # workspace = load_workspace(workspace_dir)
    
    
    engine_flow = EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        from chipcompiler.rtl2gds import build_rtl2gds_flow
        steps = build_rtl2gds_flow()
        for step, tool, state in steps:
            engine_flow.add_step(step=step, tool=tool, state=state)
            
    engine_flow.create_step_workspaces()
    
    engine_flow.run_steps()
    
def test_sg13g2_gcd():
    workspace_dir="{}/test/examples/sg13g2_gcd_tool".format(root)

    input_def = ""
    input_verilog = "{}/test/fixtures/gcd/gcd.v".format(root) # RTL file
    parameters=get_design_parameters("sg13g2", "gcd")
    parameters.data["Design"] = "gcd"
    parameters.data["Top module"] = "gcd"
    parameters.data["Clock"] = "clk"
    
    pdk_root = "{}/ihp-sg13g2".format(root)
    pdk = get_pdk("sg13g2", pdk_root=pdk_root)

    workspace = create_workspace(
        directory=workspace_dir,
        origin_def=input_def,
        origin_verilog=input_verilog,
        pdk=pdk,
        parameters=parameters
    )
    
    
    engine_flow = EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        from chipcompiler.rtl2gds import build_rtl2gds_flow
        steps = build_rtl2gds_flow()
        for step, tool, state in steps:
            engine_flow.add_step(step=step, tool=tool, state=state)
            
    engine_flow.create_step_workspaces()
    
    engine_flow.run_steps()


def test_gf180mcu_gcd(tmp_path):
    workspace_dir = tmp_path / "gf180mcu_gcd_tool"
    input_def = ""
    input_verilog = Path(root) / "test" / "fixtures" / "gcd" / "gcd.v"
    parameters = get_design_parameters("gf180mcu", "gcd")

    pdk_root = _create_minimal_gf180mcu_pdk(tmp_path / "gf180mcu")
    pdk = get_pdk("gf180mcu", pdk_root=str(pdk_root))

    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def=input_def,
        origin_verilog=str(input_verilog),
        pdk=pdk,
        parameters=parameters
    )

    engine_flow = EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        from chipcompiler.rtl2gds import build_rtl2gds_flow
        steps = build_rtl2gds_flow()
        for step, tool, state in steps:
            engine_flow.add_step(step=step, tool=tool, state=state)

    engine_flow.create_step_workspaces()
    engine_flow.run_steps()


def test_sky130_gcd(tmp_path):
    workspace_dir = tmp_path / "sky130_gcd_tool"
    input_def = ""
    input_verilog = Path(root) / "test" / "fixtures" / "gcd" / "gcd.v"
    parameters = get_design_parameters("sky130", "gcd")

    pdk_root = _create_minimal_sky130_pdk(tmp_path / "sky130")
    pdk = get_pdk("sky130", pdk_root=str(pdk_root))

    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def=input_def,
        origin_verilog=str(input_verilog),
        pdk=pdk,
        parameters=parameters
    )

    engine_flow = EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        from chipcompiler.rtl2gds import build_rtl2gds_flow
        steps = build_rtl2gds_flow()
        for step, tool, state in steps:
            engine_flow.add_step(step=step, tool=tool, state=state)

    engine_flow.create_step_workspaces()
    engine_flow.run_steps()


if __name__ == "__main__":    
    test_ics55_gcd()
    test_sg13g2_gcd()

    exit(0)
