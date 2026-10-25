"""Workspace SDC generation and refresh.

``create_default_sdc`` writes the auto-generated clock constraint file
from the workspace parameters; ``refresh_generated_sdc`` rewrites only
files ECC generated (marker-checked), so a user-provided SDC survives
parameter refreshes untouched.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chipcompiler.data import Workspace

_SDC_HEADER = """\
# ECC-generated SDC file

# -------------------------------------------------
# SDC version & units
# -------------------------------------------------
set sdc_version 2.1
set_units -time ns -resistance kOhm -capacitance pF -voltage V -current mA

# -------------------------------------------------
# Clock definition
# -------------------------------------------------
"""

_SDC_HEAD_CLOCK = """\
set clk_name      {clock}
set clk_port_name {clock}
set clk_freq_mhz  {freq_mhz}
set clk_period    [expr {{1000.0 / $clk_freq_mhz}}]

set clk_port [get_ports $clk_port_name]
create_clock -name $clk_name -period $clk_period $clk_port
set_propagated_clock [all_clocks]

set_clock_latency -source 0.5 [get_clocks $clk_name]

# -------------------------------------------------
# IO Delay
# -------------------------------------------------
set data_inputs [remove_from_collection [all_inputs] $clk_port]
set_input_delay -max 3.0 -clock [get_clocks $clk_name] $data_inputs
set_input_delay -min 1.0 -clock [get_clocks $clk_name] $data_inputs
set_output_delay -max 1.0 -clock [get_clocks $clk_name] [all_outputs]
"""

_SDC_HEAD_VIRTUAL_CLOCK = """\
set clk_name      __VIRTUAL_CLK__
set clk_freq_mhz  {freq_mhz}
set clk_period    [expr {{1000.0 / $clk_freq_mhz}}]

create_clock -name $clk_name -period $clk_period
set_clock_latency -source 0.5 [get_clocks $clk_name]

# -------------------------------------------------
# IO Delay
# -------------------------------------------------
set data_inputs [all_inputs]
set_input_delay -max 3.0 -clock [get_clocks $clk_name] $data_inputs
set_input_delay -min 1.0 -clock [get_clocks $clk_name] $data_inputs
set_output_delay -max 1.0 -clock [get_clocks $clk_name] [all_outputs]
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
set_clock_uncertainty -setup 0.20 [all_clocks]
set_clock_uncertainty -hold  0.25 [get_clocks $clk_name]
set_clock_transition        0.15 [get_clocks $clk_name]
set_input_transition        0.20 $data_inputs

# -------------------------------------------------
# Design-level constraints
# -------------------------------------------------
set_max_fanout      {max_fanout}   [current_design]
set_max_transition [expr {{$clk_period * 0.17}}] -clock_path [get_clocks $clk_name]
set_max_transition [expr {{$clk_period * 0.34}}] -data_path [get_clocks $clk_name]
set_max_capacitance 0.15 [current_design]

# -------------------------------------------------
# Timing derate (OCV)
# -------------------------------------------------
set_timing_derate -early 0.95 -clock -delay_corner [all_delay_corners]
set_timing_derate -late  1.10 -clock -delay_corner [all_delay_corners]
set_timing_derate -late  1.10 -data  -delay_corner [all_delay_corners]
"""


def create_default_sdc(workspace: "Workspace") -> None:
    """
    Create SDC file based on PDK and workspace parameters.

    A design without a clock port gets a virtual clock instead, so
    downstream tools still have a clock object as timing reference.
    """
    parameters = workspace.parameters.data
    freq_mhz = parameters.get("frequency_max", 100)

    sdc_content = _SDC_HEADER
    clock = parameters.get("clock", "")
    if clock:
        sdc_content += _SDC_HEAD_CLOCK.format(clock=clock, freq_mhz=freq_mhz)
    else:
        sdc_content += _SDC_HEAD_VIRTUAL_CLOCK.format(freq_mhz=freq_mhz)

    if workspace.pdk.sdc_load > 0:
        sdc_content += _SDC_OUTPUT_LOAD.format(
            pdk_name=workspace.pdk.name, sdc_load=workspace.pdk.sdc_load
        )

    sdc_content += _SDC_TAIL.format(max_fanout=parameters.get("max_fanout", 32))

    sdc_path = workspace.pdk.sdc
    if sdc_path is None:
        return
    with open(sdc_path, "w") as file:
        file.write(sdc_content)


def refresh_generated_sdc(workspace: "Workspace") -> None:
    """Refresh an existing SDC created by ECC while preserving user SDC files."""
    sdc_path = workspace.pdk.sdc
    if sdc_path is None or not sdc_path.is_file():
        return

    try:
        with sdc_path.open(encoding="utf-8") as file:
            marker = file.readline().strip()
            if marker not in {"# ECC-generated SDC file", "# ECC-generated clock-only SDC"}:
                return
    except (OSError, UnicodeError):
        return

    if marker == "# ECC-generated clock-only SDC":
        parameters = workspace.parameters.data
        content = "\n".join(
            (
                marker,
                "",
                f"set clk_name {parameters.get('clock', '')}",
                f"set clk_port_name {parameters.get('clock', '')}",
                f"set clk_freq_mhz {parameters.get('frequency_max', 100)}",
                "set clk_period [expr 1000.0 / $clk_freq_mhz]",
                "set clk_port [get_ports $clk_port_name]",
                "create_clock -name $clk_name -period $clk_period $clk_port",
                "",
            )
        )
        sdc_path.write_text(content)
    else:
        create_default_sdc(workspace)
