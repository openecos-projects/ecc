#!/usr/bin/env python

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import Workspace

_SDC_HEAD_CLOCK = """\
# Auto-generated SDC file

set clk_name          {clock}
set clk_port_name     {clock}
set clk_freq_mhz      {freq_mhz}
set clk_period        [expr 1000.0 / $clk_freq_mhz]
set clk_io_pct        0.2

# -------------------------------------------------
# Clock definition
# -------------------------------------------------
set clk_port [get_ports $clk_port_name]
create_clock -name $clk_name -period $clk_period $clk_port

# -------------------------------------------------
# IO Delay
# -------------------------------------------------
set clk_input          [get_ports $clk_port_name]
set all_inputs_wo_clk  [remove_from_collection [all_inputs] $clk_input]

set_input_delay  0  -clock [get_clocks $clk_name] $all_inputs_wo_clk
set_output_delay 0 -clock [get_clocks $clk_name] [all_outputs]
"""

_SDC_HEAD_VIRTUAL_CLOCK = """\
# Auto-generated SDC file

set clk_name          __VIRTUAL_CLK__
set clk_freq_mhz      {freq_mhz}
set clk_period        [expr 1000.0 / $clk_freq_mhz]
set clk_io_pct        0.2

# -------------------------------------------------
# Clock definition
# -------------------------------------------------
create_clock -name $clk_name -period $clk_period

# -------------------------------------------------
# IO Delay
# -------------------------------------------------
set all_inputs_wo_clk  [all_inputs]

set_input_delay  0  -clock [get_clocks $clk_name] $all_inputs_wo_clk
set_output_delay 0 -clock [get_clocks $clk_name] [all_outputs]
"""

_SDC_OUTPUT_LOAD = """
# -------------------------------------------------
# Output load (pF) - {pdk_name} pdk
# -------------------------------------------------
set_load {sdc_load} [all_outputs]
"""

_SDC_TAIL = """
# -------------------------------------------------
# Clock uncertainty & transition
# -------------------------------------------------
set clk_uncertainty   [expr $clk_period * 0.05]                 ;# 5% of period
set clk_transition    [expr min(0.15, $clk_period * 0.03)]      ;# 3%, cap 0.15ns
set input_transition  [expr min(0.20, $clk_period * 0.05)]      ;# 5%, cap 0.20ns

set_clock_uncertainty $clk_uncertainty  [get_clocks $clk_name]
set_clock_transition  $clk_transition   [get_clocks $clk_name]
set_input_transition  $input_transition $all_inputs_wo_clk

# -------------------------------------------------
# Design-level constraints
# -------------------------------------------------
set_max_fanout {max_fanout} [current_design]
"""


def create_default_sdc(workspace: "Workspace"):
    """
    Create SDC file based on PDK and workspace parameters.

    A design without a clock port gets a virtual clock instead, so
    downstream tools still have a clock object as timing reference.
    """
    parameters = workspace.parameters.data
    freq_mhz = parameters.get("Frequency max [MHz]", 100)

    clock = parameters.get("Clock", "")
    if clock:
        sdc_content = _SDC_HEAD_CLOCK.format(clock=clock, freq_mhz=freq_mhz)
    else:
        sdc_content = _SDC_HEAD_VIRTUAL_CLOCK.format(freq_mhz=freq_mhz)

    if workspace.pdk.sdc_load > 0:
        sdc_content += _SDC_OUTPUT_LOAD.format(
            pdk_name=workspace.pdk.name, sdc_load=workspace.pdk.sdc_load
        )

    sdc_content += _SDC_TAIL.format(max_fanout=parameters.get("Max fanout", 20))

    with open(workspace.pdk.sdc, "w") as file:
        file.write(sdc_content)
