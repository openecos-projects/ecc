import json
import shutil
import subprocess
from pathlib import Path

import pytest

from chipcompiler.data.parameter import Parameters
from chipcompiler.data.pdk import PDK
from chipcompiler.data.workspace import OriginDesign, Workspace
from chipcompiler.data.workspace.sdc import (
    create_default_sdc,
    refresh_generated_sdc,
    signoff_sdc_path,
)


@pytest.fixture
def workspace(tmp_path):
    return Workspace(
        directory=tmp_path,
        design=OriginDesign(name="design", top_module="chip"),
        pdk=PDK(sdc=tmp_path / "origin.sdc"),
        parameters=Parameters(data={"clock": "clk", "frequency_max": 100}),
    )


@pytest.fixture
def sdc_trace(tmp_path):
    """Execute actual Tcl substitution, recording only the EDA commands."""
    executable = "tclsh"
    if shutil.which(executable) is None:
        pytest.skip("Tcl interpreter not installed")
    harness = tmp_path / "trace.tcl"
    harness.write_text(
        """\
proc record {args} {
    set words {}
    foreach word $args {
        lappend words [binary encode hex [encoding convertto utf-8 $word]]
    }
    puts [join $words "\t"]
}
foreach cmd {
    set_load set_timing_derate set_clock_uncertainty
    set_max_transition set_max_fanout set_propagated_clock
    set_input_delay set_output_delay set_multicycle_path
} {
    proc $cmd {args} [format {record %s {*}$args} $cmd]
}
set clocks {}
proc create_clock {args} {
    lappend ::clocks [lindex $args 1]
    record create_clock {*}$args
}
proc get_ports {args} {
    if {[lsearch -exact $args -filter] >= 0} {
        if {[lindex $args 2] == "direction == in"} {return [all_inputs]}
        if {[lindex $args 2] == "direction == out"} {return [all_outputs]}
        error "unhandled port filter"
    }
    return [lindex $args 0]
}
proc all_inputs {} {return [list $::clk_port_name data]}
proc remove_from_collection {collection objects} {
    set result {}
    foreach item $collection {
        if {[lsearch -exact $objects $item] < 0} {lappend result $item}
    }
    return $result
}
proc get_clocks {name} {return $name}
proc all_outputs {} {return out}
proc all_clocks {} {return $::clocks}
proc current_design {} {return $::top}
source [lindex $argv 0]
if {[info exists ::injected]} {error "input executed as Tcl"}
""",
        encoding="utf-8",
    )

    command = [executable, str(harness)]

    def trace(path: Path) -> list[tuple[str | float, ...]]:
        result = subprocess.run(
            [*command, str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        calls = []
        for line in result.stdout.splitlines():
            words: list[str | float] = []
            for encoded in line.split("\t"):
                word = bytes.fromhex(encoded).decode("utf-8")
                try:
                    words.append(float(word))
                except ValueError:
                    words.append(word)
            calls.append(tuple(words))
        return calls

    return trace


@pytest.mark.parametrize("clock", ["clk", ""])
def test_generated_sdc_refresh_uses_current_design_parameters(workspace, sdc_trace, clock):
    workspace.parameters.data["clock"] = clock
    create_default_sdc(workspace)
    path = workspace.pdk.sdc
    original = path.read_text()
    expected = [("create_clock", "-name", "CLK_clk", "-period", 10.0, "clk")] if clock else []
    assert sdc_trace(path) == expected

    workspace.design.top_module = "new_chip"
    workspace.parameters.data["frequency_max"] = 250
    if clock:
        workspace.parameters.data["clock"] = "fast_clk"
    refresh_generated_sdc(workspace)

    assert path.read_text() == (
        original.replace('set top "chip"', 'set top "new_chip"')
        .replace('"clk"', '"fast_clk"')
        .replace('"CLK_clk"', '"CLK_fast_clk"')
        .replace("set clk_freq_mhz 100.0", "set clk_freq_mhz 250.0")
    )


def _configured_signoff_pairs():
    template = Path(__file__).parents[2] / "chipcompiler/tools/ecc/configs/sta_ecc.json"
    config = json.loads(template.read_text())
    return [
        (corner, rc)
        for group in config["signoff"]
        for corner, rc_corners in group.items()
        for rc in rc_corners
    ]


@pytest.mark.parametrize("corner,rc", _configured_signoff_pairs())
@pytest.mark.parametrize("frequency", [12.288, 100, 10000, 10001])
@pytest.mark.parametrize("has_io_cells", [False, True])
@pytest.mark.parametrize("phase", ["SYN", "PLACE", "CTS", "POST_CTS"])
def test_signoff_evaluates_golden_for_each_configured_pair(
    workspace, sdc_trace, corner, rc, frequency, has_io_cells, phase
):
    workspace.parameters.data["frequency_max"] = frequency
    create_default_sdc(workspace)
    original = workspace.pdk.sdc.read_bytes()
    target = workspace.directory / "sta" / corner / rc / "signoff.tcl"

    assert (
        signoff_sdc_path(
            workspace, target, phase=phase, corner=corner, rc_para=rc, has_io_cells=has_io_cells
        )
        == target
    )

    period = 1000.0 / frequency
    expected: list[tuple[str | float, ...]] = [
        ("create_clock", "-name", "CLK_clk", "-period", period, "clk")
    ]
    if has_io_cells:
        load = {"MAX": 8, "WCL": 8, "MIN": 6, "ML": 6, "TYP": 7}[corner]
        expected.append(("set_load", load, "out"))
    else:
        expected.append(("create_clock", "-name", "VCLK_clk", "-period", period))
        expected.extend(
            (command, period * fraction, bound, "-clock", "VCLK_clk", "-add_delay", ports)
            for command, ports in (("set_input_delay", "data"), ("set_output_delay", "out"))
            for fraction, bound in ((0.6, "-max"), (0.3, "-min"))
        )
        expected.extend(
            [
                ("set_multicycle_path", 4, "-setup", "-end", "-from", "clk data", "-to", "out"),
                ("set_multicycle_path", 3, "-hold", "-end", "-from", "clk data", "-to", "out"),
                ("set_load", "-max", 0.2, "out"),
                ("set_load", "-min", 0.1, "out"),
            ]
        )
    if corner == "TYP":
        expected.extend(
            [("set_timing_derate", "-late", 1.0), ("set_timing_derate", "-early", 0.95)]
        )
    else:
        early = 0.95 if corner in {"MAX", "WCL"} else 0.9
        expected.extend(
            ("set_timing_derate", delay, path, bound, factor)
            for delay in ("-cell_delay", "-net_delay")
            for path, bound, factor in (
                ("-clock", "-late", 1.0),
                ("-clock", "-early", early),
                ("-data", "-late", 1.0),
                ("-data", "-early", 1.0),
            )
        )
    clocks = "CLK_clk" if has_io_cells else "CLK_clk VCLK_clk"
    if frequency <= 10000:
        expected.extend(
            [
                ("set_clock_uncertainty", "-setup", 0.2, clocks),
                ("set_clock_uncertainty", "-hold", 0.1, clocks),
            ]
        )
    expected.extend(
        [
            ("set_max_transition", period * 0.17, "-clock_path", clocks),
            ("set_max_transition", period * 0.34, "-data_path", clocks),
            ("set_max_fanout", 32, "chip"),
        ]
    )
    if "CTS" in phase:
        expected.append(("set_propagated_clock", clocks))
    assert sdc_trace(target) == expected
    assert workspace.pdk.sdc.read_bytes() == original


@pytest.mark.parametrize(
    "content",
    [
        b"# Auto-generated SDC file\ncreate_clock -period 1.5 [get_ports clk]\n",
        "# 用户时序约束\ncreate_clock -period 1.5 [get_ports clk]\n".encode("gbk"),
    ],
)
@pytest.mark.parametrize("has_io_cells", [False, True])
@pytest.mark.parametrize("phase", ["SYN", "CTS"])
def test_custom_sdc_is_authoritative_for_refresh_and_signoff(
    workspace, content, has_io_cells, phase
):
    workspace.pdk.sdc.write_bytes(content)
    target = workspace.directory / "sta" / "signoff.tcl"

    refresh_generated_sdc(workspace)
    actual = signoff_sdc_path(
        workspace, target, phase=phase, corner="MAX", rc_para="Cworst", has_io_cells=has_io_cells
    )

    assert (actual, actual.read_bytes(), target.exists()) == (workspace.pdk.sdc, content, False)


def test_generated_names_are_literal_tcl_words(workspace, sdc_trace):
    clock = 'clk[0]$x; [set ::injected 1] " \\ {}'
    workspace.parameters.data["clock"] = clock
    workspace.design.top_module = "top[0]$top; [set ::injected 1]"
    create_default_sdc(workspace)

    assert sdc_trace(workspace.pdk.sdc) == [
        ("create_clock", "-name", f"CLK_{clock}", "-period", 10.0, clock)
    ]


def test_clockless_core_uses_core_loads_without_inventing_a_virtual_clock(workspace, sdc_trace):
    workspace.parameters.data["clock"] = ""
    create_default_sdc(workspace)
    target = workspace.directory / "sta" / "signoff.tcl"

    signoff_sdc_path(
        workspace, target, phase="CTS", corner="TYP", rc_para="TYPICAL", has_io_cells=False
    )

    assert sdc_trace(target) == [
        ("set_load", "-max", 0.2, "out"),
        ("set_load", "-min", 0.1, "out"),
        ("set_timing_derate", "-late", 1.0),
        ("set_timing_derate", "-early", 0.95),
        ("set_max_fanout", 32, "chip"),
        ("set_propagated_clock", ""),
    ]


def test_generated_phase_controls_propagation_at_tcl_execution(workspace, sdc_trace):
    create_default_sdc(workspace)
    target = workspace.directory / "signoff.tcl"
    signoff_sdc_path(
        workspace, target, phase="CTS", corner="TYP", rc_para="TYPICAL", has_io_cells=False
    )
    post_cts_calls = sdc_trace(target)
    target.write_text(target.read_text().replace('set phase "CTS"', 'set phase "SYN"'))

    assert post_cts_calls[-1] == ("set_propagated_clock", "CLK_clk VCLK_clk")
    assert sdc_trace(target) == post_cts_calls[:-1]


@pytest.mark.parametrize("frequency", [0, -1, float("inf"), float("nan")])
def test_invalid_clock_frequency_does_not_replace_sdc(workspace, frequency):
    create_default_sdc(workspace)
    original = workspace.pdk.sdc.read_bytes()
    workspace.parameters.data["frequency_max"] = frequency

    with pytest.raises(ValueError, match="finite and positive"):
        refresh_generated_sdc(workspace)

    assert workspace.pdk.sdc.read_bytes() == original
