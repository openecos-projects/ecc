import pytest

from chipcompiler.data.workspace.primary_clocks import PrimaryClock, parse_primary_clocks


def test_literal_clock_commands_preserve_names_periods_and_sources():
    clocks = parse_primary_clocks(
        """
        # User clocks, with periods in ns.
        create_clock -period 12.5 -name {CPU} -waveform {1 6} \\
            [get_ports -quiet {clk[0]}]; # bus port
        create_clock -name "PLL" -period 2.5 [get_pins {u_pll/clk.out[1]}]
        """
    )
    assert clocks == (
        PrimaryClock("clk[0]", 80, "CPU", "port", (1, 6)),
        PrimaryClock("u_pll/clk.out[1]", 400, "PLL", "pin"),
    )
    assert tuple((clock.name, clock.period) for clock in clocks) == (("CPU", 12.5), ("PLL", 2.5))


@pytest.mark.parametrize("text", ["", "\n# Nothing enabled\n"])
def test_empty_primary_clock_commands(text):
    assert parse_primary_clocks(text) == ()


@pytest.mark.parametrize(
    "command, message",
    [
        ("create_clock -period 10 [get_ports clk]", "-name and -period are required"),
        ("create_clock -name clk [get_ports clk]", "-name and -period are required"),
        ("create_clock -name clk -period 10 -period 20 [get_ports clk]", "duplicate -period"),
        ("create_clock -name {} -period 10 [get_ports clk]", "nonempty literal name"),
        ("create_clock -name clk -period 0 [get_ports clk]", "finite positive"),
        ("create_clock -name clk -period -1 [get_ports clk]", "finite positive"),
        ("create_clock -name clk -period nan [get_ports clk]", "finite positive"),
        ("create_clock -name clk -period inf [get_ports clk]", "finite positive"),
        ("create_clock -name clk -period 1e-320 [get_ports clk]", "finite positive"),
        ("create_clock -name clk -period 1_000 [get_ports clk]", "finite positive"),
        ("create_clock -name clk -period 10 -waveform {0} [get_ports clk]", "two numeric edges"),
        ("create_clock -name clk -period 10 -waveform {5 1} [get_ports clk]", "increasing"),
        ("create_clock -name clk -period 10 -waveform {0 1e999} [get_ports clk]", "finite"),
        ("create_clock -name clk -period 10 [get_ports {clk aux}]", "one literal port/pin"),
        ("create_clock -name clk -period 10 [get_ports clk*]", "not a list or wildcard"),
        ("create_clock -name clk -period $period [get_ports clk]", "not Tcl expressions"),
        ("create_clock -name clk -period [expr 10] [get_ports clk]", "not Tcl expressions"),
        ("create_clock -name clk -period 10 -add [get_ports clk]", "expected create_clock"),
        ("create_clock -name clk -period 10", "expected create_clock"),
        ("create_clock -name clk -period 10 [get_ports clk]; puts unexpected", "one command"),
    ],
)
def test_invalid_or_dynamic_primary_clock_is_not_guessed(command, message):
    with pytest.raises(ValueError, match=message):
        parse_primary_clocks(command)


@pytest.mark.parametrize(
    "second, message",
    [
        ("create_clock -name CPU -period 20 [get_ports aux]", "duplicate clock name"),
        ("create_clock -name AUX -period 20 [get_ports clk]", "duplicate clock target"),
    ],
)
def test_duplicate_primary_clock_identity_is_rejected(second, message):
    with pytest.raises(ValueError, match=message):
        parse_primary_clocks("create_clock -name CPU -period 10 [get_ports clk]\n" + second)
