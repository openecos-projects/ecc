#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os
from chipcompiler.data import WorkspaceStep, Workspace, Parameters, StepEnum


def build_step(workspace: Workspace,
               step_name: str,
               input_def: str,
               input_verilog: str,
               output_def: str = None,
               output_verilog: str = None,
               output_gds: str = None) -> WorkspaceStep:
    """
    Build the synthesis step in the specified workspace.

    Note: input_def is not used for synthesis, only input_verilog (RTL).
    Synthesis doesn't produce DEF; output_def points to verilog for flow compatibility.
    """
    step = WorkspaceStep()
    step.name = step_name
    step.tool = "yosys"
    step.version = "0.1"

    step.directory = f"{workspace.directory}/{step.name}_{step.tool}"

    step.config = {
        "dir": f"{step.directory}/config",
    }

    step.input = {
        "verilog": input_verilog,
    }

    if output_verilog is None:
        output_verilog = f"{step.directory}/output/{workspace.design.name}_{step.name}.v"
    if output_def is None:
        output_def = output_verilog
    step.output = {
        "dir": f"{step.directory}/output",
        "def": output_def,
        "verilog": output_verilog,
        "json": f"{step.directory}/output/{workspace.design.name}_{step.name}.json",
        "report": f"{step.directory}/output/{workspace.design.name}_{step.name}.rpt",
    }

    step.data = {
        "dir": f"{step.directory}/data",
        "tmp": f"{step.directory}/data/tmp",
    }

    step.report = {
        "dir": f"{step.directory}/report",
        "stat": f"{step.directory}/report/{step.name}_stat.json",
        "check": f"{step.directory}/report/{step.name}_check.rpt",
    }

    step.log = {
        "dir": f"{step.directory}/log",
        "file": f"{step.directory}/log/{step.name}.log",
    }

    step.script = {
        "dir": f"{step.directory}/script",
        "main": f"{step.directory}/script/{step.name}_main.tcl",
    }

    return step


def build_step_space(step: WorkspaceStep) -> None:
    """
    Create the workspace directories for the given step.
    """
    os.makedirs(step.directory, exist_ok=True)
    os.makedirs(step.config.get("dir", f"{step.directory}/config"), exist_ok=True)
    os.makedirs(step.output.get("dir", f"{step.directory}/output"), exist_ok=True)
    os.makedirs(step.data.get("dir", f"{step.directory}/data"), exist_ok=True)
    os.makedirs(step.data.get("tmp", f"{step.directory}/data/tmp"), exist_ok=True)
    os.makedirs(step.report.get("dir", f"{step.directory}/report"), exist_ok=True)
    os.makedirs(step.log.get("dir", f"{step.directory}/log"), exist_ok=True)
    os.makedirs(step.script.get("dir", f"{step.directory}/script"), exist_ok=True)


def build_step_config(workspace: Workspace,
                      step: WorkspaceStep,
                      parameters: Parameters):
    """
    Build the configuration files for the synthesis step.

    Creates the following directory structure in data/:
    - scripts/ subdirectory with all TCL scripts (yosys_synthesis.tcl, global_var.tcl, init_tech.tcl, abc-opt.script)
    - tmp/ subdirectory for generated files and AIG library
    """
    import shutil

    current_dir = os.path.dirname(os.path.abspath(__file__))
    scripts_dir = os.path.abspath(os.path.join(current_dir, 'scripts'))

    # Create scripts subdirectory in data/
    scripts_subdir = os.path.join(step.data['dir'], 'scripts')
    os.makedirs(scripts_subdir, exist_ok=True)

    # Copy all scripts to scripts/ subdirectory
    for file in ['yosys_synthesis.tcl', 'global_var.tcl', 'init_tech.tcl', 'abc-opt.script']:
        src = os.path.join(scripts_dir, file)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(scripts_subdir, file))

    # Copy LMS library (AIG file) to tmp/ subdirectory
    configs_dir = os.path.abspath(os.path.join(current_dir, 'configs'))
    aig_file = os.path.join(configs_dir, 'lazy_man_synth_library.aig')
    # TODO: Move to other folder if needed?
    if os.path.exists(aig_file):
        shutil.copy2(aig_file, os.path.join(step.data['tmp'], 'lazy_man_synth_library.aig'))

