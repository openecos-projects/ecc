import json
from pathlib import Path

from chipcompiler.data import get_design_parameters, get_parameters
from chipcompiler.data.parameter import (
    Parameters,
    load_parameter,
    parameters_have_chip_identity,
    reload_parameter,
    save_parameter,
)


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


def test_get_design_parameters_ics55_unknown_design_returns_base_template():
    parameters = get_design_parameters("ics55", "unknown_design")

    assert parameters.data["Design"] == ""
    assert parameters.data["Top module"] == ""
    assert parameters.data["Clock"] == ""
    assert parameters.data["Frequency max [MHz]"] == 100


def test_get_parameters_returns_independent_copies():
    first = get_parameters("ics55")
    second = get_parameters("ics55")

    first.data["Design"] = "mutated"
    first.data["Core"]["Margin"][0] = 999

    assert second.data["Design"] == ""
    assert second.data["Core"]["Margin"][0] == 2


def test_ics55_template_has_dreamplace_padding_defaults():
    parameters = get_parameters("ics55")

    assert parameters.data["Cell padding x"] == 300
    assert parameters.data["Routability opt flag"] == 1


# SG13G2 parameter tests


def test_get_parameters_sg13g2_returns_template():
    parameters = get_parameters("sg13g2")

    assert parameters.data["PDK"] == "sg13g2"
    assert parameters.data["Design"] == ""
    assert parameters.data["Top module"] == ""
    assert parameters.data["Clock"] == ""
    assert parameters.data["Frequency max [MHz]"] == 100


def test_get_parameters_sg13g2_returns_independent_copies():
    first = get_parameters("sg13g2")
    second = get_parameters("sg13g2")

    first.data["Design"] = "mutated"
    first.data["Floorplan"]["Tracks"][0]["x step"] = 999

    assert second.data["Design"] == ""
    assert second.data["Floorplan"]["Tracks"][0]["x step"] == 420


def test_sg13g2_template_has_correct_layer_names():
    parameters = get_parameters("sg13g2")

    assert parameters.data["Bottom layer"] == "Metal2"
    assert parameters.data["Top layer"] == "Metal5"


def test_sg13g2_template_has_correct_core_defaults():
    parameters = get_parameters("sg13g2")

    assert parameters.data["Core"]["Utilitization"] == 0.65
    assert parameters.data["Core"]["Margin"] == [17.5, 17.5]
    assert parameters.data["Target density"] == 0.65


def test_sg13g2_template_has_dreamplace_padding_defaults():
    parameters = get_parameters("sg13g2")

    assert parameters.data["Cell padding x"] == 0
    assert parameters.data["Routability opt flag"] == 1


def test_sg13g2_template_pdn_has_two_power_nets():
    parameters = get_parameters("sg13g2")

    io_nets = parameters.data["PDN"]["IO"]
    assert len(io_nets) == 2
    net_names = [n["net name"] for n in io_nets]
    assert "VDD" in net_names
    assert "VSS" in net_names


def test_get_design_parameters_sg13g2_returns_base_template():
    """SG13G2 has no design-specific overrides, so any design name returns the base template."""
    parameters = get_design_parameters("sg13g2", "gcd")

    assert parameters.data["PDK"] == "sg13g2"
    assert parameters.data["Design"] == ""
    assert parameters.data["Top module"] == ""


def test_load_parameter_accepts_path_and_stores_path_object(tmp_path):
    path = tmp_path / "parameters.json"
    path.write_text(json.dumps({"Design": "gcd"}))

    parameters = load_parameter(path)

    assert isinstance(parameters.path, Path)
    assert parameters.path == path
    assert parameters.data["Design"] == "gcd"


def test_get_parameters_accepts_path_and_save_writes_to_path(tmp_path):
    path = tmp_path / "parameters.json"

    parameters = get_parameters("ics55", path)
    parameters.data["Design"] = "gcd"

    assert isinstance(parameters.path, Path)
    assert parameters.path == path
    assert save_parameter(parameters)
    assert json.loads(path.read_text())["Design"] == "gcd"


def test_get_parameters_without_path_uses_none():
    parameters = get_parameters("ics55")

    assert parameters.path is None


def test_parameters_have_chip_identity_requires_dashboard_fields():
    assert parameters_have_chip_identity({}) is False
    assert parameters_have_chip_identity({"Die": {"Size": [], "Area": 0}}) is False
    assert parameters_have_chip_identity({"PDK": "ics55"}) is True
    assert parameters_have_chip_identity({"Design": "gcd"}) is True
    assert parameters_have_chip_identity({"Top module": "gcd"}) is True
    assert parameters_have_chip_identity({"Clock": "clk"}) is True
    assert parameters_have_chip_identity({"Die": {"Area": 1200}}) is True


def test_reload_parameter_keeps_identity_when_file_is_empty(tmp_path):
    path = tmp_path / "parameters.json"
    path.write_text("{}")
    current = Parameters(
        path=path,
        data={
            "PDK": "ics55",
            "Design": "gcd",
            "Top module": "gcd",
            "Clock": "clk",
            "Die": {"Size": [100, 80], "Area": 8000},
        },
    )

    reloaded = reload_parameter(path, current)

    assert reloaded.data["PDK"] == "ics55"
    assert reloaded.data["Design"] == "gcd"
    assert reloaded.data["Top module"] == "gcd"
    assert reloaded.data["Clock"] == "clk"
    assert reloaded.data["Die"]["Area"] == 8000
    assert reloaded.path == path
