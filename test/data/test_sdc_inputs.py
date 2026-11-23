import pytest

from chipcompiler.data.workspace.sdc_inputs import (
    EXPLICIT_FREQUENCY_KEY,
    PrimaryClock,
    SdcInputs,
    parse_clock_list,
)


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


def test_explicit_frequency_replaces_the_first_clock_in_every_corner():
    inputs = SdcInputs(clock_list="clk MAX:90 TYP:100\nclk_aux MAX:20 TYP:25\n")

    # design.frequency_mhz set on top of the list: synthesis reads it, so the
    # constraints describe the same primary clock; other clocks are untouched.
    explicit = {"clock": "clk", "frequency_max": 150, EXPLICIT_FREQUENCY_KEY: True}
    for corner, auxiliary in (("MAX", 20), ("TYP", 25)):
        assert inputs.clocks(explicit, corner) == (
            PrimaryClock("clk", 150),
            PrimaryClock("clk_aux", auxiliary),
        )


@pytest.mark.parametrize("frequency_max", [100.0, 150, None, "fast"])
def test_frequency_metadata_alone_leaves_the_clock_list_in_charge(frequency_max):
    """A frequency_max that differs from the list is not an explicit setting."""
    inputs = SdcInputs(clock_list="clk MAX:90 TYP:100\nclk_aux MAX:20 TYP:25\n")

    assert inputs.clocks({"clock": "clk", "frequency_max": frequency_max}, "MAX") == (
        PrimaryClock("clk", 90),
        PrimaryClock("clk_aux", 20),
    )


@pytest.mark.parametrize("frequency_max", [None, "fast", 0, -5])
def test_unusable_explicit_frequency_leaves_the_clock_list_in_charge(frequency_max):
    inputs = SdcInputs(clock_list="clk MAX:90 TYP:100\n")
    parameters = {"frequency_max": frequency_max, EXPLICIT_FREQUENCY_KEY: True}

    assert inputs.clocks(parameters, "MAX") == (PrimaryClock("clk", 90),)


def _workspace(tmp_path, parameters):
    from chipcompiler.data.parameter import Parameters
    from chipcompiler.data.pdk import PDK
    from chipcompiler.data.workspace import OriginDesign, Workspace

    return Workspace(
        directory=tmp_path,
        design=OriginDesign(name="chip"),
        pdk=PDK(),
        parameters=Parameters(data=parameters),
    )


def _primary(workspace, corner):
    data = workspace.parameters.data
    return SdcInputs.from_parameters(data).clocks(data, corner)[0]


def test_legacy_workspace_clock_list_supplies_the_primary_clock(tmp_path):
    workspace = _workspace(
        tmp_path,
        {"clock": "clk", "frequency_max": 100.0, "sdc": {"clock_list": "clk MAX:180 TYP:200"}},
    )

    assert _primary(workspace, "MAX") == PrimaryClock("clk", 180)
    assert _primary(workspace, "TYP") == PrimaryClock("clk", 200)


def test_workspace_frequency_override_replaces_the_first_clock_until_it_is_unset(tmp_path):
    from chipcompiler.data.parameter_schema import lookup_schema
    from chipcompiler.data.workspace.parameters import (
        unset_workspace_param,
        update_workspace_param_value,
    )

    workspace = _workspace(
        tmp_path,
        {"clock": "clk", "frequency_max": 100.0, "sdc": {"clock_list": "clk MAX:90 TYP:100"}},
    )
    schema = lookup_schema("design.frequency_mhz")

    update_workspace_param_value(workspace, schema, 150.0)
    assert _primary(workspace, "MAX") == PrimaryClock("clk", 150)
    assert _primary(workspace, "TYP") == PrimaryClock("clk", 150)

    unset_workspace_param(workspace, schema)
    assert _primary(workspace, "MAX") == PrimaryClock("clk", 90)
    assert _primary(workspace, "TYP") == PrimaryClock("clk", 100)


def test_workspace_override_equal_to_its_baseline_is_not_an_explicit_frequency():
    inputs = SdcInputs(clock_list="clk MAX:90 TYP:100\n")
    record = {"key": "design.frequency_mhz", "baseline": 100.0, "value": 100.0}
    parameters = {"frequency_max": 100.0, "workspace_param_overrides": [record]}

    assert inputs.clocks(parameters, "MAX") == (PrimaryClock("clk", 90),)


def test_explicit_frequency_marker_survives_a_params_toml_round_trip(tmp_path):
    from chipcompiler.data.parameter import Parameters, load_parameter, save_parameter

    path = tmp_path / "home" / "params.toml"
    path.parent.mkdir()
    saved = Parameters(
        data={
            "clock": "clk",
            "frequency_max": 150.0,
            EXPLICIT_FREQUENCY_KEY: True,
            "sdc": {"clock_list": "clk MAX:90 TYP:100\n"},
        },
        path=path,
    )
    assert save_parameter(saved)

    data = load_parameter(path).data
    assert data[EXPLICIT_FREQUENCY_KEY] is True
    assert SdcInputs.from_parameters(data).clocks(data, "MAX") == (PrimaryClock("clk", 150),)


def test_explicit_frequency_marker_is_carried_into_a_rebuilt_workspace():
    """A refresh rebuilds the parameters: the frequency and how it was set stay together."""
    from chipcompiler.params import carried_parameters

    explicit = {
        "pdk": "ics55",
        "clock": "clk",
        "frequency_max": 150.0,
        EXPLICIT_FREQUENCY_KEY: True,
        "sdc": {"clock_list": "clk MAX:90 TYP:100\n"},
    }
    carried = carried_parameters(explicit)
    assert carried["frequency_max"] == 150.0
    assert carried[EXPLICIT_FREQUENCY_KEY] is True
    assert SdcInputs.from_parameters(carried).clocks(carried, "MAX") == (PrimaryClock("clk", 150),)

    derived = {key: value for key, value in explicit.items() if key != EXPLICIT_FREQUENCY_KEY}
    carried = carried_parameters(derived)
    assert EXPLICIT_FREQUENCY_KEY not in carried
    assert SdcInputs.from_parameters(carried).clocks(carried, "MAX") == (PrimaryClock("clk", 90),)
