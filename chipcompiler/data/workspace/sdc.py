"""Generate pre/post-CTS golden timing-constraint Tcl.

The two scenario sets share golden rules; only post-CTS propagates clocks.
Custom full constraint files remain authoritative and are never supplemented.
"""

import math
import re
from pathlib import Path
from typing import TYPE_CHECKING

from chipcompiler.utility.file import write_text_atomic

if TYPE_CHECKING:
    from chipcompiler.data import Workspace

_GENERATED_MARKER = "# ECC-generated SDC file"


def _section(title: str) -> list[str]:
    separator = "# " + "-" * 76
    return ["", separator, f"# {title}", separator]


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


def _design_constraints(workspace: "Workspace") -> list[str]:
    lines = [
        _GENERATED_MARKER,
        *_section("1. Design and flow context"),
        f"set top {_tcl_word(workspace.design.top_module or workspace.design.name)}",
        *_section("2. Primary clock - user design input resolved by ECC"),
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
                "create_clock -name $clk_name -period $clk_period \\",
                "    [get_ports $clk_port_name]",
            ]
        )
    return lines


def is_generated_sdc(path: Path | None) -> bool:
    if path is None or not path.is_file():
        return False
    with path.open("rb") as stream:
        return stream.readline().strip() == _GENERATED_MARKER.encode("ascii")


def signoff_sdc_path(
    workspace: "Workspace",
    output_path: Path,
    *,
    post_cts: bool,
    corner: str,
    rc_para: str,
    has_io_cells: bool | None = None,
) -> Path:
    """Write a standalone scenario with IO rules selected from the loaded design."""
    source = workspace.pdk.sdc
    if source is not None and not is_generated_sdc(source):
        return source

    lines = _design_constraints(workspace)
    lines.extend(
        [
            *_section("3. Signoff scenario - selected by ECC"),
            f"set corner {_tcl_word(corner)}",
            f"set rc_para {_tcl_word(rc_para)}",
            *_section("4. IO interface constraints - golden branch selected from iDB"),
        ]
    )
    if has_io_cells is None:
        lines.append('error "ECC must load the design before selecting timing IO constraints"')
    else:
        lines.extend(_io_constraints(workspace, corner, has_io_cells=has_io_cells))

    clock = workspace.parameters.data.get("clock", "")
    lines.extend(_section("5. OCV derate - first matching golden rule"))
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
        lines.extend(_section("6. Clock uncertainty - setup and hold margins"))
        if frequency <= 10000:
            lines.extend(
                [
                    "set_clock_uncertainty -setup 0.200 [all_clocks]",
                    "set_clock_uncertainty -hold 0.1 [all_clocks]",
                ]
            )
        lines.extend(
            [
                *_section("7. Maximum transition - scaled by the clock period"),
                "set_max_transition [expr {$clk_period * 0.17}] \\",
                "    -clock_path [all_clocks]",
                "set_max_transition [expr {$clk_period * 0.34}] \\",
                "    -data_path [all_clocks]",
            ]
        )
    lines.extend(
        [
            *_section("8. Design-level electrical constraints"),
            "set_max_fanout 32 [current_design]",
        ]
    )
    if post_cts:
        lines.extend(_section("9. Propagated clocks"))
        lines.append("set_propagated_clock [all_clocks]")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + "\n"
    if not output_path.exists() or output_path.read_text(encoding="utf-8") != text:
        write_text_atomic(output_path, text)
    return output_path


def _io_constraints(workspace: "Workspace", corner: str, *, has_io_cells: bool) -> list[str]:
    lines = []
    clock = workspace.parameters.data.get("clock", "")
    if has_io_cells:
        lines.extend(["", "# 4.1 Output load"])
        if re.search(r"WCZ|WCL|MAX", corner):
            load = 8
        elif re.search(r"ML|MZ|MIN", corner):
            load = 6
        else:
            load = 7
        lines.append(f"set_load {load} [all_outputs]")
    else:
        if clock:
            lines.extend(
                [
                    "",
                    "# 4.1 Virtual interface clock",
                    f"set virtual_clk_name {_tcl_word(f'VCLK_{clock}')}",
                    "create_clock -name $virtual_clk_name -period $clk_period",
                    "",
                    "# 4.2 IO delay budget",
                    "set data_inputs [remove_from_collection \\",
                    "    [get_ports -quiet -filter {direction == in} *] "
                    "[get_ports $clk_port_name]]",
                    "set data_outputs [get_ports -quiet -filter {direction == out} *]",
                    "",
                    "if {[llength $data_inputs]} {",
                    "    set_input_delay [expr {$clk_period * 0.6}] -max \\",
                    "        -clock $virtual_clk_name -add_delay $data_inputs",
                    "    set_input_delay [expr {$clk_period * 0.3}] -min \\",
                    "        -clock $virtual_clk_name -add_delay $data_inputs",
                    "}",
                    "",
                    "if {[llength $data_outputs]} {",
                    "    set_output_delay [expr {$clk_period * 0.6}] -max \\",
                    "        -clock $virtual_clk_name -add_delay $data_outputs",
                    "    set_output_delay [expr {$clk_period * 0.3}] -min \\",
                    "        -clock $virtual_clk_name -add_delay $data_outputs",
                    "}",
                    "",
                    "# 4.3 Input-to-output multicycles",
                    "set_multicycle_path 4 -setup -end \\",
                    "    -from [all_inputs] -to [all_outputs]",
                    "set_multicycle_path 3 -hold -end \\",
                    "    -from [all_inputs] -to [all_outputs]",
                ]
            )
        lines.extend(
            [
                "",
                "# 4.4 Core output load",
                "set_load -max 0.2 [all_outputs]",
                "set_load -min 0.1 [all_outputs]",
            ]
        )

    return lines
