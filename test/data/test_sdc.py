import json
import shutil
import subprocess
from pathlib import Path

import pytest

from chipcompiler.data.parameter import Parameters
from chipcompiler.data.pdk import PDK
from chipcompiler.data.workspace import OriginDesign, Workspace
from chipcompiler.data.workspace.sdc import signoff_sdc_path
from chipcompiler.data.workspace.timing_constraints import generate_timing_scripts


@pytest.fixture
def workspace(tmp_path):
    return Workspace(
        directory=tmp_path,
        design=OriginDesign(name="design", top_module="chip"),
        pdk=PDK(),
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
    set_input_delay set_output_delay set_multicycle_path set_false_path set_clock_groups
} {
    proc $cmd {args} [format {record %s {*}$args} $cmd]
}
set clocks {}
set explicit_ports [lindex $argv 1]
proc create_clock {args} {
    set name [lindex $args [expr {[lsearch -exact $args -name] + 1}]]
    set period [lindex $args [expr {[lsearch -exact $args -period] + 1}]]
    lappend ::clocks $name
    set ::periods($name) $period
    if {[llength $args] == 5} {
        set ::source_clock([lindex $args end]) $name
    }
    record create_clock {*}$args
}
proc create_generated_clock {args} {
    set name [lindex $args [expr {[lsearch -exact $args -name] + 1}]]
    set source [lindex $args [expr {[lsearch -exact $args -source] + 1}]]
    set divide [lindex $args [expr {[lsearch -exact $args -divide_by] + 1}]]
    lappend ::clocks $name
    set ::periods($name) [expr {$::periods($::source_clock($source)) * $divide}]
    record create_generated_clock {*}$args
}
proc get_attribute {clock attribute} {
    if {$attribute ne "period"} {error "unhandled clock attribute"}
    return $::periods($clock)
}
proc foreach_in_collection {variable objects body} {
    uplevel 1 [list foreach $variable $objects $body]
}
proc get_ports {args} {
    if {[lsearch -exact $args -filter] >= 0} {
        if {[lindex $args 2] == "direction == in"} {return [all_inputs]}
        if {[lindex $args 2] == "direction == out"} {return [all_outputs]}
        error "unhandled port filter"
    }
    set patterns [lindex $args end]
    if {![llength $::explicit_ports]} {return $patterns}
    set matches {}
    foreach pattern $patterns {
        foreach port $::explicit_ports {
            if {$pattern eq $port || [string match $pattern $port]} {lappend matches $port}
        }
    }
    return [lsort -unique $matches]
}
proc get_pins {name} {return $name}
proc all_inputs {} {
    if {[llength $::explicit_ports]} {
        return [remove_from_collection $::explicit_ports [all_outputs]]
    }
    return [list $::clk_port_name data]
}
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
set input_file [open [lindex $argv 0] r]
set input_text [read $input_file]
close $input_file
eval $input_text
if {[info exists ::injected]} {error "input executed as Tcl"}
""",
        encoding="utf-8",
    )

    command = [executable, str(harness)]

    def trace(path: Path, *, ports: tuple[str, ...] = ()) -> list[tuple[str | float, ...]]:
        result = subprocess.run(
            [*command, str(path), " ".join(ports)],
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
def test_generated_constraints_refresh_uses_current_design_parameters(workspace, sdc_trace, clock):
    workspace.parameters.data["clock"] = clock
    generate_timing_scripts(workspace, has_io_cells=True)
    path = workspace.pdk.sdc
    original = path.read_text()
    expected = [("create_clock", "-name", "CLK_clk", "-period", 10.0, "clk")] if clock else []
    assert [call for call in sdc_trace(path) if call[0] == "create_clock"] == expected

    workspace.design.top_module = "new_chip"
    workspace.parameters.data["frequency_max"] = 250
    if clock:
        workspace.parameters.data["clock"] = "fast_clk"
    generate_timing_scripts(workspace, has_io_cells=True)

    assert path.read_text() == (
        original.replace('set top "chip"', 'set top "new_chip"')
        .replace('"clk"', '"fast_clk"')
        .replace('"CLK_clk"', '"CLK_fast_clk"')
        .replace('"VCLK_clk"', '"VCLK_fast_clk"')
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
@pytest.mark.parametrize("post_cts", [False, True])
def test_signoff_evaluates_golden_for_each_configured_pair(
    workspace, sdc_trace, corner, rc, frequency, has_io_cells, post_cts
):
    workspace.parameters.data["frequency_max"] = frequency
    generate_timing_scripts(workspace, has_io_cells=has_io_cells)
    original = workspace.pdk.sdc.read_bytes()
    target = workspace.directory / "sta" / corner / rc / "signoff.tcl"

    assert (
        signoff_sdc_path(
            workspace,
            target,
            post_cts=post_cts,
            corner=corner,
            rc_para=rc,
            has_io_cells=has_io_cells,
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
    if post_cts:
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
@pytest.mark.parametrize("post_cts", [False, True])
def test_custom_sdc_is_authoritative_for_refresh_and_signoff(
    workspace, content, has_io_cells, post_cts
):
    workspace.pdk.sdc = workspace.directory / "custom.sdc"
    workspace.pdk.sdc.write_bytes(content)
    target = workspace.directory / "sta" / "signoff.tcl"

    generate_timing_scripts(workspace, has_io_cells=has_io_cells)
    actual = signoff_sdc_path(
        workspace,
        target,
        post_cts=post_cts,
        corner="MAX",
        rc_para="Cworst",
        has_io_cells=has_io_cells,
    )

    assert (actual, actual.read_bytes(), target.exists()) == (workspace.pdk.sdc, content, False)


def test_generated_names_are_literal_tcl_words(workspace, sdc_trace):
    clock = 'clk[0]$x; [set ::injected 1] " \\ {}'
    workspace.parameters.data["clock"] = clock
    workspace.design.top_module = "top[0]$top; [set ::injected 1]"
    generate_timing_scripts(workspace, has_io_cells=True)

    assert [call for call in sdc_trace(workspace.pdk.sdc) if call[0] == "create_clock"] == [
        ("create_clock", "-name", f"CLK_{clock}", "-period", 10.0, clock)
    ]


def test_clockless_core_uses_core_loads_without_inventing_a_virtual_clock(workspace, sdc_trace):
    workspace.parameters.data["clock"] = ""
    generate_timing_scripts(workspace, has_io_cells=False)
    target = workspace.directory / "sta" / "signoff.tcl"

    signoff_sdc_path(
        workspace, target, post_cts=True, corner="TYP", rc_para="TYPICAL", has_io_cells=False
    )

    assert sdc_trace(target) == [
        ("set_load", "-max", 0.2, "out"),
        ("set_load", "-min", 0.1, "out"),
        ("set_timing_derate", "-late", 1.0),
        ("set_timing_derate", "-early", 0.95),
        ("set_max_fanout", 32, "chip"),
        ("set_propagated_clock", ""),
    ]


def test_pre_and_post_cts_only_differ_in_propagation(workspace, sdc_trace):
    generate_timing_scripts(workspace, has_io_cells=False)
    paths = [workspace.directory / "pre.tcl", workspace.directory / "post.tcl"]
    for path, post_cts in zip(paths, (False, True), strict=True):
        signoff_sdc_path(
            workspace, path, post_cts=post_cts, corner="TYP", rc_para="TYPICAL", has_io_cells=False
        )
    pre_calls, post_calls = map(sdc_trace, paths)
    assert post_calls == [*pre_calls, ("set_propagated_clock", "CLK_clk VCLK_clk")]
    assert paths[1].read_text().startswith(paths[0].read_text())


@pytest.mark.parametrize("frequency", [0, -1, float("inf"), float("nan")])
def test_invalid_clock_frequency_does_not_replace_sdc(workspace, frequency):
    generate_timing_scripts(workspace, has_io_cells=False)
    original = workspace.pdk.sdc.read_bytes()
    workspace.parameters.data["frequency_max"] = frequency

    with pytest.raises(ValueError, match="finite and positive"):
        generate_timing_scripts(workspace, has_io_cells=False)

    assert workspace.pdk.sdc.read_bytes() == original


def test_unknown_io_requires_preparation_before_tcl_execution(workspace, sdc_trace):
    generate_timing_scripts(workspace)
    with pytest.raises(subprocess.CalledProcessError) as exc:
        sdc_trace(workspace.pdk.sdc)
    assert "ECC must load the design before selecting timing IO constraints" in exc.value.stderr

    generate_timing_scripts(workspace, has_io_cells=False)
    assert sdc_trace(workspace.pdk.sdc)[0] == (
        "create_clock",
        "-name",
        "CLK_clk",
        "-period",
        10.0,
        "clk",
    )


@pytest.mark.parametrize("corner,period", [("TYP", 10.0), ("MAX", 20.0)])
@pytest.mark.parametrize("has_io_cells", [True, False])
@pytest.mark.parametrize("post_cts", [True, False])
@pytest.mark.parametrize("generated", [True, False])
def test_user_inputs_execute_in_order_with_per_clock_golden_limits(
    workspace, sdc_trace, corner, period, has_io_cells, post_cts, generated
):
    first_group = "CLK_clk CLK_div2" if generated else "CLK_clk"
    workspace.parameters.data["sdc"] = {
        "clock_list": "clk TYP:100 MAX:50\naux TYP:25 MAX:25\nu_pll/Q TYP:200 MAX:200",
        "generated_clock_txt": "create_generated_clock -name CLK_div2 -divide_by 2 \\\n"
        "    -source [get_ports clk] [get_pins u_div/Q]",
        "clk_group_txt": (
            f"set_clock_groups -asynchronous -group {{{first_group}}} -group {{CLK_aux}}"
        ),
        "io_constraint_txt": "set_input_delay 0.7 -max -clock CLK_clk [get_ports data]",
        "timing_exception_txt": "set_false_path -from [get_ports reset_n]",
    }
    if not generated:
        workspace.parameters.data["sdc"]["generated_clock_txt"] = ""
    target = workspace.directory / "constraints.tcl"
    signoff_sdc_path(
        workspace,
        target,
        post_cts=post_cts,
        corner=corner,
        rc_para="Cworst",
        has_io_cells=has_io_cells,
    )
    expected = []
    periods = {}
    for name, clock_period, source in (
        ("CLK_clk", period, "clk"),
        ("CLK_aux", 40.0, "aux"),
        ("CLK_u_pll_Q", 5.0, "u_pll/Q"),
    ):
        expected.append(("create_clock", "-name", name, "-period", clock_period, source))
        periods[name] = clock_period
        if not has_io_cells and "/" not in source:
            expected.append(("create_clock", "-name", f"V{name}", "-period", clock_period))
            periods[f"V{name}"] = clock_period
    if generated:
        expected.append(
            (
                "create_generated_clock",
                "-name",
                "CLK_div2",
                "-divide_by",
                2.0,
                "-source",
                "clk",
                "u_div/Q",
            )
        )
        periods["CLK_div2"] = period * 2
    expected.append(
        ("set_clock_groups", "-asynchronous", "-group", first_group, "-group", "CLK_aux")
    )
    if has_io_cells:
        expected.append(("set_load", 8.0 if corner == "MAX" else 7.0, "out"))
    else:
        for name, clock_period in (("VCLK_clk", period), ("VCLK_aux", 40.0)):
            for command, objects in (
                ("set_input_delay", "data reset_n"),
                ("set_output_delay", "out"),
            ):
                for bound, fraction in (("-max", 0.6), ("-min", 0.3)):
                    expected.append(
                        (
                            command,
                            clock_period * fraction,
                            bound,
                            "-clock",
                            name,
                            "-add_delay",
                            objects,
                        )
                    )
            expected.extend(
                [
                    (
                        "set_multicycle_path",
                        4.0,
                        "-setup",
                        "-end",
                        "-from",
                        "clk aux data reset_n",
                        "-to",
                        "out",
                    ),
                    (
                        "set_multicycle_path",
                        3.0,
                        "-hold",
                        "-end",
                        "-from",
                        "clk aux data reset_n",
                        "-to",
                        "out",
                    ),
                ]
            )
        expected.extend([("set_load", "-max", 0.2, "out"), ("set_load", "-min", 0.1, "out")])
    expected.extend(
        [
            ("set_input_delay", 0.7, "-max", "-clock", "CLK_clk", "data"),
            ("set_false_path", "-from", "reset_n"),
        ]
    )
    if corner == "MAX":
        expected.extend(
            (
                "set_timing_derate",
                f"-{delay}_delay",
                f"-{path}",
                f"-{bound}",
                0.95 if (path, bound) == ("clock", "early") else 1.0,
            )
            for delay in ("cell", "net")
            for path in ("clock", "data")
            for bound in ("late", "early")
        )
    else:
        expected.extend(
            [("set_timing_derate", "-late", 1.0), ("set_timing_derate", "-early", 0.95)]
        )
    for name in periods:
        expected.extend(
            [
                ("set_clock_uncertainty", "-setup", 0.2, name),
                ("set_clock_uncertainty", "-hold", 0.1, name),
            ]
        )
    for name, clock_period in periods.items():
        expected.extend(
            [
                ("set_max_transition", clock_period * 0.17, "-clock_path", name),
                ("set_max_transition", clock_period * 0.34, "-data_path", name),
            ]
        )
    expected.append(("set_max_fanout", 32.0, "chip"))
    if post_cts:
        expected.append(("set_propagated_clock", " ".join(periods)))
    assert sdc_trace(target, ports=("clk", "aux", "data", "reset_n", "out")) == expected


def test_generated_clock_uses_default_primary_and_its_own_frequency_band(workspace, sdc_trace):
    workspace.parameters.data["frequency_max"] = 20000
    workspace.parameters.data["sdc"] = {
        "generated_clock_txt": "create_generated_clock -name CLK_div2 -divide_by 2 "
        "-source [get_ports clk] [get_pins u_div/Q]",
    }
    generate_timing_scripts(workspace, has_io_cells=True)
    calls = sdc_trace(workspace.pdk.sdc, ports=("clk", "data", "out"))
    assert [call for call in calls if call[0] == "set_clock_uncertainty"] == [
        ("set_clock_uncertainty", "-setup", 0.2, "CLK_div2"),
        ("set_clock_uncertainty", "-hold", 0.1, "CLK_div2"),
    ]
    assert [call for call in calls if call[0] == "set_max_transition"] == [
        ("set_max_transition", 0.05 * 0.17, "-clock_path", "CLK_clk"),
        ("set_max_transition", 0.05 * 0.34, "-data_path", "CLK_clk"),
        ("set_max_transition", 0.1 * 0.17, "-clock_path", "CLK_div2"),
        ("set_max_transition", 0.1 * 0.34, "-data_path", "CLK_div2"),
    ]


def test_invalid_user_corner_does_not_partially_replace_scenario_files(workspace):
    generate_timing_scripts(workspace, has_io_cells=True)
    previous = {path: path.read_bytes() for path in (workspace.directory / "origin").rglob("*.tcl")}
    workspace.parameters.data["sdc"] = {"clock_list": "clk MAX:50"}
    with pytest.raises(ValueError, match="no frequency for corner"):
        generate_timing_scripts(workspace, has_io_cells=False)
    assert {path: path.read_bytes() for path in previous} == previous


def test_full_custom_constraints_bypass_user_input_parsing(workspace):
    custom = workspace.directory / "full.tcl"
    custom.write_text("# User-owned complete Tcl\nset custom 1\n")
    workspace.pdk.sdc = custom
    workspace.parameters.data["sdc"] = {"clock_list": "invalid clock list"}
    generate_timing_scripts(workspace, has_io_cells=False)
    assert (
        signoff_sdc_path(
            workspace,
            workspace.directory / "ignored.tcl",
            post_cts=True,
            corner="TYP",
            rc_para="TYPICAL",
        )
        == custom
    )
    assert custom.read_text() == "# User-owned complete Tcl\nset custom 1\n"


def test_commented_examples_do_not_change_executed_defaults(workspace, sdc_trace):
    generate_timing_scripts(workspace, has_io_cells=False)
    expected = sdc_trace(workspace.pdk.sdc)
    workspace.parameters.data["sdc"] = {
        "clock_list": "# clk MAX:50 TYP:100",
        "generated_clock_txt": "# create_generated_clock -name CLK_unused ...\n",
        "clk_group_txt": "# set_clock_groups -asynchronous ...\n",
        "io_constraint_txt": "# set_input_delay 999 -clock CLK_unused ...\n",
        "timing_exception_txt": "# set_false_path -from ...\n",
    }
    generate_timing_scripts(workspace, has_io_cells=False)
    assert sdc_trace(workspace.pdk.sdc) == expected
