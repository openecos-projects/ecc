"""Generate design clocks and CX55 signoff constraints.

The origin SDC describes the design, not a particular analysis corner. STA
specializes the signoff golden for each PVT/RC pair in ``sta_ecc.json``. The
reference flow calls post-layout analysis ``CTS``; it is not the CTS operation.
User-supplied SDCs remain authoritative and are never rewritten or supplemented.
"""

import math
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chipcompiler.data import Workspace

_GENERATED_MARKER = "# ECC-generated SDC file"


def _tcl_word(value: str) -> str:
    """Quote one literal Tcl word, including bus indices and hierarchy names."""
    escapes = str.maketrans(
        {"\\": "\\\\", '"': '\\"', "$": "\\$", "[": "\\[", "]": "\\]", "\n": "\\n", "\r": "\\r"}
    )
    return '"' + value.translate(escapes) + '"'


def _clock_frequency(workspace: "Workspace") -> float:
    frequency = float(workspace.parameters.data.get("frequency_max", 100))
    if not math.isfinite(frequency) or frequency <= 0:
        raise ValueError("SDC clock frequency must be finite and positive (MHz)")
    return frequency


def _design_constraints(workspace: "Workspace", phase: str) -> list[str]:
    lines = [
        _GENERATED_MARKER,
        "# Design constraints; time values are in ns, frequency in MHz.",
        "# Remove the ECC marker before maintaining this file as a custom SDC.",
        f"set top {_tcl_word(workspace.design.top_module or workspace.design.name)}",
        f"set phase {_tcl_word(phase)}",
        "",
        "# Primary clock from the ECC design parameters.",
    ]
    clock = workspace.parameters.data.get("clock", "")
    if clock:
        frequency = _clock_frequency(workspace)
        lines.extend(
            [
                f"set clk_port_name {_tcl_word(clock)}",
                f"set clk_name {_tcl_word(f'CLK_{clock}')}",
                f"set clk_freq_mhz {frequency}",
                "set clk_period [expr {1000.0 / $clk_freq_mhz}]",
                "create_clock -name $clk_name -period $clk_period [get_ports $clk_port_name]",
            ]
        )
    return lines


def _is_generated(path: Path) -> bool:
    with path.open("rb") as stream:
        return stream.readline().strip() == _GENERATED_MARKER.encode("ascii")


def create_default_sdc(workspace: "Workspace") -> None:
    """Write design clocks without assuming a signoff corner or built clock tree.

    ECC's default design interface declares a single clock port and frequency.
    Design-specific clocks, groups, IO delays and exceptions require a custom SDC.
    The golden IO policy is selected at signoff after loading the physical design.
    A clockless design does not acquire an invented virtual clock.
    """
    if workspace.pdk.sdc is not None:
        workspace.pdk.sdc.write_text(
            "\n".join(_design_constraints(workspace, "SYN")) + "\n", encoding="utf-8"
        )


def refresh_generated_sdc(workspace: "Workspace") -> None:
    """Refresh only the common SDC owned by this generator."""
    path = workspace.pdk.sdc
    if path is not None and path.is_file() and _is_generated(path):
        create_default_sdc(workspace)


def signoff_sdc_path(
    workspace: "Workspace", output_path: Path, *, corner: str, rc_para: str, has_io_cells: bool
) -> Path:
    """Materialize the golden for one post-layout STA job, or return custom SDC.

    ``corner`` and ``rc_para`` come from the same signoff item as the Liberty/SPEF
    inputs, never from a guessed global default. Actual instantiated IO cells
    select the golden's father-empty branch; bare cores select father-nonempty.
    Each job owns its file so parallel STA cannot overwrite shared constraints.
    """
    source = workspace.pdk.sdc
    if source is None:
        raise ValueError("Signoff STA requires an SDC path")
    if not _is_generated(source):
        return source

    lines = _design_constraints(workspace, "CTS")
    lines.extend(
        [
            "",
            "# Signoff context from sta_ecc.json.",
            f"set corner {_tcl_word(corner)}",
            f"set rc_para {_tcl_word(rc_para)}",
            "# Output loads use the library capacitance units.",
        ]
    )
    clock = workspace.parameters.data.get("clock", "")
    if has_io_cells:
        lines.extend(["", "# IO cells present: chip interface (father is empty)."])
        if re.search(r"WCZ|WCL|MAX", corner):
            load = 8
        elif re.search(r"ML|MZ|MIN", corner):
            load = 6
        else:
            load = 7
        lines.append(f"set_load {load} [all_outputs]")
    else:
        lines.extend(["", "# No IO cells: core interface (father is nonempty), auto_io_const=YES."])
        if clock:
            lines.extend(
                [
                    f"set virtual_clk_name {_tcl_word(f'VCLK_{clock}')}",
                    "create_clock -name $virtual_clk_name -period $clk_period",
                    "set data_inputs [remove_from_collection "
                    "[get_ports -quiet -filter {direction == in} *] [get_ports $clk_port_name]]",
                    "set data_outputs [get_ports -quiet -filter {direction == out} *]",
                    "if {[llength $data_inputs]} {",
                    "    set_input_delay [expr {$clk_period * 0.6}] -max "
                    "-clock $virtual_clk_name -add_delay $data_inputs",
                    "    set_input_delay [expr {$clk_period * 0.3}] -min "
                    "-clock $virtual_clk_name -add_delay $data_inputs",
                    "}",
                    "if {[llength $data_outputs]} {",
                    "    set_output_delay [expr {$clk_period * 0.6}] -max "
                    "-clock $virtual_clk_name -add_delay $data_outputs",
                    "    set_output_delay [expr {$clk_period * 0.3}] -min "
                    "-clock $virtual_clk_name -add_delay $data_outputs",
                    "}",
                    "set_multicycle_path 4 -setup -end -from [all_inputs] -to [all_outputs]",
                    "set_multicycle_path 3 -hold -end -from [all_inputs] -to [all_outputs]",
                ]
            )
        lines.extend(["set_load -max 0.2 [all_outputs]", "set_load -min 0.1 [all_outputs]"])

    lines.extend(["", "# OCV: first matching golden group, then its default group."])
    slow = re.search(r"(?:MAX|WCL)$", corner) and (
        rc_para.endswith("worst") or "default" in rc_para
    )
    fast = re.search(r"(?:MIN|ML)$", corner)
    if slow or fast:
        early_clock = 0.95 if slow else 0.9
        for delay in ("cell", "net"):
            for path in ("clock", "data"):
                for bound in ("late", "early"):
                    factor = early_clock if (path, bound) == ("clock", "early") else 1.0
                    lines.append(f"set_timing_derate -{delay}_delay -{path} -{bound} {factor}")
    else:
        lines.extend(["set_timing_derate -late 1.0", "set_timing_derate -early 0.95"])

    if clock:
        frequency = _clock_frequency(workspace)
        lines.extend(["", "# Clock uncertainty: the golden interval is (0, 10000] MHz."])
        if frequency <= 10000:
            lines.extend(
                [
                    "set_clock_uncertainty -setup 0.200 [all_clocks]",
                    "set_clock_uncertainty -hold 0.1 [all_clocks]",
                ]
            )
        lines.extend(
            [
                "",
                "# Maximum transition: 17% for clock paths, 34% for data paths.",
                "set_max_transition [expr {$clk_period * 0.17}] -clock_path [all_clocks]",
                "set_max_transition [expr {$clk_period * 0.34}] -data_path [all_clocks]",
            ]
        )
    lines.extend(["", "# Signoff fanout limit.", "set_max_fanout 32 [current_design]"])
    if clock:
        lines.extend(
            [
                "",
                "# Post-layout signoff (the reference flow's CTS phase).",
                "set_propagated_clock [all_clocks]",
            ]
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
