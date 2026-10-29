"""Generate design clocks and full-chip CX55 signoff constraints.

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
        "# Full-chip constraints; time values are in ns, frequency in MHz.",
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
    Generated clocks, clock groups, IO delays and timing exceptions require a
    user-supplied SDC. A clockless design does not acquire an invented virtual clock.
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
    workspace: "Workspace", output_path: Path, *, corner: str, rc_para: str
) -> Path:
    """Materialize the golden for one post-layout STA job, or return custom SDC.

    ``corner`` and ``rc_para`` come from the same signoff item as the Liberty/SPEF
    inputs, never from a guessed global default. Each job owns its output file so
    parallel STA cannot overwrite another job's constraints or the origin SDC.
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
            "# Signoff context from sta_ecc.json; complete chip top (father is empty).",
            f"set corner {_tcl_word(corner)}",
            f"set rc_para {_tcl_word(rc_para)}",
            "# auto_io_const=YES only adds automatic IO constraints for submodules.",
            "# A full chip has no default IO delays, clock latency or input transition.",
            "",
            "# Output load: use the golden's library capacitance units.",
        ]
    )
    if re.search(r"WCZ|WCL|MAX", corner):
        load = 8
    elif re.search(r"ML|MZ|MIN", corner):
        load = 6
    else:
        load = 7
    lines.append(f"set_load {load} [all_outputs]")

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

    clock = workspace.parameters.data.get("clock", "")
    if clock:
        frequency = _clock_frequency(workspace)
        lines.extend(["", "# Clock uncertainty: the golden interval is (0, 10000] MHz."])
        if frequency <= 10000:
            lines.extend(
                [
                    "set_clock_uncertainty -setup 0.200 [get_clocks $clk_name]",
                    "set_clock_uncertainty -hold 0.1 [get_clocks $clk_name]",
                ]
            )
        lines.extend(
            [
                "",
                "# Maximum transition: 17% for clock paths, 34% for data paths.",
                "set_max_transition [expr {$clk_period * 0.17}] -clock_path [get_clocks $clk_name]",
                "set_max_transition [expr {$clk_period * 0.34}] -data_path [get_clocks $clk_name]",
            ]
        )
    lines.extend(["", "# Full-chip signoff fanout limit.", "set_max_fanout 32 [current_design]"])
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
