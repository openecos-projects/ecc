import tomllib
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

    assert parameters.data["design"] == "gcd"
    assert parameters.data["top_module"] == "gcd"
    assert parameters.data["clock"] == "clk"
    assert parameters.data["frequency_max"] == 100


def test_get_design_parameters_ics55_empty_design_returns_base_template():
    parameters = get_design_parameters("ics55", "")

    assert parameters.data["design"] == ""
    assert parameters.data["top_module"] == ""
    assert parameters.data["clock"] == ""
    assert parameters.data["frequency_max"] == 100


def test_get_design_parameters_ics55_unknown_design_returns_base_template():
    parameters = get_design_parameters("ics55", "unknown_design")

    assert parameters.data["design"] == ""
    assert parameters.data["top_module"] == ""
    assert parameters.data["clock"] == ""
    assert parameters.data["frequency_max"] == 100


def test_get_parameters_returns_independent_copies():
    first = get_parameters("ics55")
    second = get_parameters("ics55")

    first.data["design"] = "mutated"
    first.data["core"]["margin"][0] = 999

    assert second.data["design"] == ""
    assert second.data["core"]["margin"][0] == 2


def test_ics55_template_has_dreamplace_padding_defaults():
    parameters = get_parameters("ics55")

    assert parameters.data["cell_padding_x"] == 300
    assert parameters.data["routability_opt_flag"] == 1


# SG13G2 parameter tests


def test_get_parameters_sg13g2_returns_template():
    parameters = get_parameters("sg13g2")

    assert parameters.data["pdk"] == "sg13g2"
    assert parameters.data["design"] == ""
    assert parameters.data["top_module"] == ""
    assert parameters.data["clock"] == ""
    assert parameters.data["frequency_max"] == 100


def test_get_parameters_sg13g2_returns_independent_copies():
    first = get_parameters("sg13g2")
    second = get_parameters("sg13g2")

    first.data["design"] = "mutated"
    first.data["floorplan"]["tracks"][0]["x_step"] = 999

    assert second.data["design"] == ""
    assert second.data["floorplan"]["tracks"][0]["x_step"] == 420


def test_sg13g2_template_has_correct_layer_names():
    parameters = get_parameters("sg13g2")

    assert parameters.data["bottom_layer"] == "Metal2"
    assert parameters.data["top_layer"] == "Metal5"


def test_sg13g2_template_has_correct_core_defaults():
    parameters = get_parameters("sg13g2")

    assert parameters.data["core"]["utilitization"] == 0.65
    assert parameters.data["core"]["margin"] == [17.5, 17.5]
    assert parameters.data["target_density"] == 0.65


def test_sg13g2_template_has_dreamplace_padding_defaults():
    parameters = get_parameters("sg13g2")

    assert parameters.data["cell_padding_x"] == 0
    assert parameters.data["routability_opt_flag"] == 1


def test_sg13g2_template_pdn_has_two_power_nets():
    parameters = get_parameters("sg13g2")

    io_nets = parameters.data["pdn"]["io"]
    assert len(io_nets) == 2
    net_names = [n["net_name"] for n in io_nets]
    assert "VDD" in net_names
    assert "VSS" in net_names


def test_get_design_parameters_sg13g2_returns_base_template():
    """SG13G2 has no design-specific overrides, so any design name returns the base template."""
    parameters = get_design_parameters("sg13g2", "gcd")

    assert parameters.data["pdk"] == "sg13g2"
    assert parameters.data["design"] == ""
    assert parameters.data["top_module"] == ""


def test_load_parameter_reads_workspace_config(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    config_path = home / "params.toml"
    config_path.write_text('[params]\ndesign = "gcd"\n')

    parameters = load_parameter(config_path)

    assert isinstance(parameters.path, Path)
    assert parameters.path == config_path
    assert parameters.data["design"] == "gcd"


def test_load_parameter_missing_file_returns_empty(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    parameters = load_parameter(home / "params.toml")

    assert parameters.data == {}


def test_get_parameters_accepts_path_and_save_writes_to_path(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    path = home / "params.toml"

    parameters = get_parameters("ics55", path)
    parameters.data["design"] = "gcd"

    assert isinstance(parameters.path, Path)
    assert parameters.path == path
    assert save_parameter(parameters)
    with open(path, "rb") as f:
        assert tomllib.load(f)["params"]["design"] == "gcd"


def test_get_parameters_without_path_uses_none():
    parameters = get_parameters("ics55")

    assert parameters.path is None


def test_parameters_have_chip_identity_requires_identity_fields():
    assert parameters_have_chip_identity({}) is False
    assert parameters_have_chip_identity({"die": {"size": [], "area": 0}}) is False
    assert parameters_have_chip_identity({"pdk": "ics55"}) is True
    assert parameters_have_chip_identity({"design": "gcd"}) is True
    assert parameters_have_chip_identity({"top_module": "gcd"}) is True
    assert parameters_have_chip_identity({"clock": "clk"}) is True
    assert parameters_have_chip_identity({"die": {"area": 1200}}) is True


def test_reload_parameter_keeps_identity_when_file_is_empty(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    path = home / "params.toml"
    path.write_text("")
    current = Parameters(
        path=path,
        data={
            "pdk": "ics55",
            "design": "gcd",
            "top_module": "gcd",
            "clock": "clk",
            "die": {"size": [100, 80], "area": 8000},
        },
    )

    reloaded = reload_parameter(path, current)

    assert reloaded.data["pdk"] == "ics55"
    assert reloaded.data["design"] == "gcd"
    assert reloaded.data["top_module"] == "gcd"
    assert reloaded.data["clock"] == "clk"
    assert reloaded.data["die"]["area"] == 8000
    assert reloaded.path == path
