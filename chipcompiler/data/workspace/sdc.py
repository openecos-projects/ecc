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

    No-clock designs get a minimal placeholder SDC (no create_clock).
    """
    from chipcompiler.data.workspace_config import coerce_bool, flow_no_clock

    data = getattr(getattr(workspace, "parameters", None), "data", None)
    no_clock = False
    if isinstance(data, dict):
        no_clock = coerce_bool(data.get("no_clock")) or flow_no_clock(data.get("_flow"))

    if no_clock:
        with open(workspace.pdk.sdc, "w") as file:
            file.write("# Auto-generated SDC for no-clock design\n")
        return

    sdc_content = []
    sdc_content.append("# Auto-generated SDC file\n")
    sdc_content.append("\n")
    sdc_content.append("set clk_name {} \n".format(workspace.parameters.data.get("clock", "")))
    sdc_content.append("set clk_port_name {}\n".format(workspace.parameters.data.get("clock", "")))
    sdc_content.append(
        "set clk_freq_mhz {}\n".format(workspace.parameters.data.get("frequency_max", 100))
    )
    sdc_content.append("set clk_period [expr 1000.0 / $clk_freq_mhz]\n")
    sdc_content.append("set clk_io_pct 0.2\n")
    sdc_content.append("set clk_port [get_ports $clk_port_name]\n")
    sdc_content.append("create_clock -name $clk_name -period $clk_period $clk_port\n")

    with open(workspace.pdk.sdc, "w") as file:
        file.writelines(sdc_content)


def refresh_generated_sdc(workspace: "Workspace") -> None:
    """Refresh an existing SDC created by ECC while preserving user SDC files."""
    sdc_path = workspace.pdk.sdc
    if sdc_path is None or not sdc_path.is_file():
        return

    try:
        with sdc_path.open(encoding="utf-8") as file:
            first_line = file.readline().strip()
            if first_line not in {
                "# Auto-generated SDC file",
                "# Auto-generated SDC for no-clock design",
            }:
                return
    except (OSError, UnicodeError):
        return

    create_default_sdc(workspace)
