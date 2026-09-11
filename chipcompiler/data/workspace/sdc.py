"""Workspace SDC generation and refresh.

``create_default_sdc`` writes the auto-generated clock constraint file
from the workspace parameters; ``refresh_generated_sdc`` rewrites only
files ECC generated (marker-checked), so a user-provided SDC survives
parameter refreshes untouched.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chipcompiler.data import Workspace


def create_default_sdc(workspace: "Workspace") -> None:
    """
    Create SDC file based on PDK and workspace parameters.
    """
    clock = workspace.parameters.data.get("clock", "")
    freq_mhz = workspace.parameters.data.get("frequency_max", 100)
    max_fanout = workspace.parameters.data.get("max_fanout", 20)

    sdc_content = f"""\
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

    if workspace.pdk.sdc_load > 0:
        sdc_content += f"""
# -------------------------------------------------
# Output load (pF) - {workspace.pdk.name} pdk
# -------------------------------------------------
set_load {workspace.pdk.sdc_load} [all_outputs]
"""

    sdc_content += f"""
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

    with open(workspace.pdk.sdc, "w") as file:
        file.write(sdc_content)


def refresh_generated_sdc(workspace: "Workspace") -> None:
    """Refresh an existing SDC created by ECC while preserving user SDC files."""
    sdc_path = workspace.pdk.sdc
    if sdc_path is None or not sdc_path.is_file():
        return

    try:
        with sdc_path.open(encoding="utf-8") as file:
            if file.readline().strip() != "# Auto-generated SDC file":
                return
    except (OSError, UnicodeError):
        return

    create_default_sdc(workspace)
