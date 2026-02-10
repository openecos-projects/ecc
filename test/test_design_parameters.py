import pytest

from chipcompiler.data import get_design_parameters, get_parameters


def test_get_design_parameters_ics55_gcd_overrides_fields():
    parameters = get_design_parameters("ics55", "gcd")

    assert parameters.data["Design"] == "gcd"
    assert parameters.data["Top module"] == "gcd"
    assert parameters.data["Clock"] == "clk"
    assert parameters.data["Frequency max [MHz]"] == 100


def test_get_design_parameters_ics55_empty_design_returns_base_template():
    parameters = get_design_parameters("ics55", "")

    assert parameters.data["Design"] == ""
    assert parameters.data["Top module"] == ""
    assert parameters.data["Clock"] == ""
    assert parameters.data["Frequency max [MHz]"] == 100


def test_get_design_parameters_ics55_unknown_design_raises():
    with pytest.raises(ValueError, match="Unsupported ICS55 design"):
        get_design_parameters("ics55", "unknown_design")


def test_get_parameters_returns_independent_copies():
    first = get_parameters("ics55")
    second = get_parameters("ics55")

    first.data["Design"] = "mutated"
    first.data["Floorplan"]["Tracks"][0]["x step"] = 999

    assert second.data["Design"] == ""
    assert second.data["Floorplan"]["Tracks"][0]["x step"] == 200
