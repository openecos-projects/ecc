#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import subprocess
import os
from chipcompiler.data import WorkspaceStep, Workspace, StateEnum, StepEnum
from chipcompiler.tools.yosys.utility import is_eda_exist, get_yosys_command


def run_step(workspace: Workspace,
             step: WorkspaceStep,
             module=None) -> bool:
    """
    Run the synthesis step using yosys.

    Args:
        workspace: The workspace containing design info
        step: The step workspace with paths and config
        module: Not used for yosys (kept for API compatibility)

    Returns:
        True if synthesis succeeded, False otherwise

    Environment variables set for global_var.tcl:
        - TOP_NAME: Top module name
        - CLK_FREQ_MHZ: Clock frequency in MHz
        - RTL_FILE: Input RTL file path
        - NETLIST_FILE: Output netlist path
        - LIB_STDCELL, LIB_ALL: Liberty files
        - CELL_TIE_LOW/HIGH and ports: Tie cell configurations
        - RESULT_DIR: Output directory
    """
    if not is_eda_exist():
        return False

    input_verilog = step.input.get("verilog", "")
    if not input_verilog or not os.path.exists(input_verilog):
        print(f"Error: RTL file not found: {input_verilog}")
        return False

    try:
        cwd_dir = step.data.get("dir", step.directory)
        env = os.environ.copy()

        env["TOP_NAME"] = workspace.design.top_module

        freq_mhz = workspace.parameters.data.get("Frequency max [MHz]", 100)
        env["CLK_FREQ_MHZ"] = str(freq_mhz)

        env["RTL_FILE"] = step.input.get("verilog", "")

        env["NETLIST_FILE"] = step.output["verilog"]
        env["TIMING_CELL_STAT_RPT"] = step.report.get("stat", "")
        env["TIMING_CELL_COUNT_RPT"] = step.report.get("check", "")
        env["GENERIC_STAT_JSON"] = step.report.get("stat", "")
        env["SYNTH_STAT_JSON"] = step.report.get("stat", "")
        env["SYNTH_CHECK_RPT"] = step.report.get("check", "")

        env["KEEP_HIERARCHY"] = "false"

        dont_use_cells = workspace.parameters.data.get("Dont use cells", [])
        env["CELL_DONT_USE"] = " ".join(dont_use_cells) if dont_use_cells else ""

        env["CELL_TIE_LOW"] = workspace.parameters.data.get("Tie low cell", "")
        env["CELL_TIE_LOW_PORT"] = workspace.parameters.data.get("Tie low port", "")
        env["CELL_TIE_HIGH"] = workspace.parameters.data.get("Tie high cell", "")
        env["CELL_TIE_HIGH_PORT"] = workspace.parameters.data.get("Tie high port", "")

        lib_files = workspace.pdk.libs
        env["LIB_STDCELL"] = lib_files[0] if lib_files else ""
        env["LIB_ALL"] = " ".join(lib_files)

        env["RESULT_DIR"] = cwd_dir

        yosys_cmd = get_yosys_command()
        if not yosys_cmd:
            print("Error: No yosys installation found")
            return False

        cmd = yosys_cmd + ["scripts/yosys_synthesis.tcl"]

        with open(step.log["file"], "w") as log_file:
            result = subprocess.run(
                cmd,
                cwd=cwd_dir,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                timeout=600
            )

        if os.path.exists(step.output["verilog"]):
            return True
        else:
            print(f"Error: Output netlist not generated at {step.output['verilog']}")
            return False

    except subprocess.TimeoutExpired:
        print("Error: Yosys synthesis timed out")
        return False
    except Exception as e:
        print(f"Error running yosys: {e}")
        return False
