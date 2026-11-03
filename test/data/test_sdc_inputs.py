import pytest

from chipcompiler.data.workspace.sdc_inputs import PrimaryClock, SdcInputs, parse_clock_list


def test_clock_list_resolves_corner_frequencies_and_internal_pin_names():
    inputs = SdcInputs(
        clock_list="""
            # clocks in MHz
            clk[0] MAX : 100 TYP:125 ; # port
            u_pll/clk.out[1] MAX:12.288 TYP:25
        """
    )
    clocks = inputs.clocks({}, "MAX")
    assert clocks == (PrimaryClock("clk[0]", 100), PrimaryClock("u_pll/clk.out[1]", 12.288))
    assert tuple(clock.name for clock in clocks) == ("CLK_clk[0]", "CLK_u_pll_clk_out_1")
    assert inputs.clocks({}, "TYP") == (
        PrimaryClock("clk[0]", 125),
        PrimaryClock("u_pll/clk.out[1]", 25),
    )


@pytest.mark.parametrize("text", ["", "\n# no clock override\n"])
def test_empty_clock_list_uses_existing_clock_metadata(text):
    inputs = SdcInputs(clock_list=text)
    assert inputs.clocks({"clock": "clk", "frequency_max": 12.288}, "TYP") == (
        PrimaryClock("clk", 12.288),
    )
    assert inputs.clocks({"clock": ""}, "MAX") == ()


@pytest.mark.parametrize(
    "text, message",
    [
        ("clk", "expected target"),
        ("clk TYP:0", "finite and positive"),
        ("clk TYP:-10", "finite and positive"),
        ("clk TYP:nan", "finite and positive"),
        ("clk TYP:inf", "finite and positive"),
        ("clk TYP:100.0oops", "finite and positive"),
        ("clk TYP:100 TYP:200", "duplicate corner"),
        ("clk TYP:100\nclk TYP:200", "duplicate target"),
        ("clk garbage TYP:100", "invalid corner:MHz"),
        ("clk TYP:100 trailing", "invalid corner:MHz"),
    ],
)
def test_clock_list_rejects_invalid_rows(text, message):
    with pytest.raises(ValueError, match=message):
        parse_clock_list(text)


def test_clock_list_requires_the_requested_corner_and_unique_clock_names():
    with pytest.raises(ValueError, match="no frequency for corner MIN"):
        SdcInputs(clock_list="clk TYP:100").clocks({}, "MIN")
    with pytest.raises(ValueError, match="duplicate clock names"):
        SdcInputs(clock_list="u/pll.Q TYP:100\nu/pll/Q TYP:100").clocks({}, "TYP")
