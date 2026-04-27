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
    first.data["Floorplan"]["Tracks"][0]["x step"] = 999

    assert second.data["Design"] == ""
    assert second.data["Floorplan"]["Tracks"][0]["x step"] == 200


def test_ics55_template_has_dreamplace_padding_defaults():
    parameters = get_parameters("ics55")

    assert parameters.data["Cell padding x"] == 600
    assert parameters.data["Routability opt flag"] == 1


#SG13G2 parameter tests

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
