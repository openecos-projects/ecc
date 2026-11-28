"""Run the native IO-cell placer on a small pad-level netlist."""

import gzip
import re
from pathlib import Path

from chipcompiler.data import StepEnum, create_workspace
from chipcompiler.data.parameter import get_design_parameters
from chipcompiler.tools.ecc.builder import build_step, build_step_config, build_step_space
from chipcompiler.tools.ecc.runner import run_step


def test_pre_floorplan_places_signal_pad_and_exports_its_port(tmp_path, minimal_ics55_pdk_factory):
    design = Path(__file__).parent / "fixtures" / "io_pad"
    netlist = design / "pad_top.v"
    parameters = get_design_parameters("ics55", "pad_top").data
    parameters.update(
        design="pad_top",
        top_module="pad_top",
        clock="",
        die={"size": [200, 200]},
        geometry={"snapshot": False},
        config_overrides={
            "floorplan": {
                "io_placer": {
                    "mode": "io_cell",
                    "io_cell": {"definition_file_path": str(design / "io.json")},
                },
                "pdn_generator": {"core_power_net": "VDD", "core_ground_net": "VSS"},
            }
        },
    )
    workspace = create_workspace(
        directory=tmp_path / "workspace",
        origin_def="",
        origin_verilog=netlist,
        pdk="ics55",
        pdk_root=minimal_ics55_pdk_factory(tmp_path / "pdk"),
        pdk_overrides={"tech": str(design / "tech.lef"), "lefs": [str(design / "cells.lef")]},
        parameters=parameters,
    )
    assert workspace is not None
    step = build_step(workspace, StepEnum.PRE_FLOORPLAN, None, netlist)
    build_step_space(step)
    build_step_config(workspace, step)
    assert run_step(workspace, step)
    assert step.output.def_ is not None
    with gzip.open(step.output.def_, "rt") as output:
        layout = output.read()
    assert re.search(r"- u_signal PAD_SIG\s+\+ (?:PLACED|FIXED)", layout)
    assert re.search(r"- pad \+ NET pad\b[^;]+\+ LAYER MET4\b[^;]+\+ FIXED", layout)
