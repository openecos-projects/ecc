"""The user-file boundary accepts structured timing data, not executable SDC."""

import tomllib

import pytest
import tomli_w

from chipcompiler.cli.project.timing_template import SDC_INPUT_TEMPLATE
from chipcompiler.data.workspace.sdc_inputs import SdcInputs


def test_file_round_trip_preserves_all_groups_and_derives_clock_metadata(tmp_path):
    values = tomllib.loads(SDC_INPUT_TEMPLATE)
    values.update(
        primary_clocks="create_clock -name REF -period 12.5 [get_ports ref_clk]\n"
        "create_clock -name PLL -period 5 [get_pins u_pll/Q]\n",
        generated_clocks="create_generated_clock -name div2 -divide_by 2 \\\n"
        "    -source [get_ports ref_clk] [get_pins u_div/Q]\n",
        clock_groups="# same clock domain\n",
        io_constraints="set_input_delay 0.3 -clock REF [get_ports {req[0]}]\n",
        timing_exceptions="set_false_path -from [get_ports test_mode]\n",
    )
    path = tmp_path / "design.tcl"
    content = tomli_w.dumps(values)
    path.write_text(content)
    inputs = SdcInputs.from_file(path)
    snapshot = {
        "primary_clocks": values["primary_clocks"],
        "clock_list": "",
        "generated_clock_txt": values["generated_clocks"],
        "clk_group_txt": values["clock_groups"],
        "io_constraint_txt": values["io_constraints"],
        "timing_exception_txt": values["timing_exceptions"],
    }
    assert inputs == SdcInputs(**snapshot)
    assert inputs.parameters() == {"sdc": snapshot, "clock": "ref_clk", "frequency_max": 80}
    assert inputs.clocks({}, "TYP") == inputs.clocks({}, "MIN")
    assert path.read_text() == content


@pytest.mark.parametrize(
    "content, message",
    [
        ("create_clock -period 10 [get_ports clk]\n", "not a full SDC/Tcl script"),
        ("primary_clocks = '''unterminated", "expected five TOML string fields"),
        ("[params.sdc]\n" + SDC_INPUT_TEMPLATE, "five fields at the file root"),
        (SDC_INPUT_TEMPLATE + "unexpected = 'value'\n", "unknown="),
        ("primary_clocks = ''\n", "missing="),
    ],
)
def test_file_schema_rejects_invalid_input(tmp_path, content, message):
    path = tmp_path / "bad.tcl"
    path.write_text(content)
    with pytest.raises(ValueError, match=message):
        SdcInputs.from_file(path)
    assert path.read_text() == content


@pytest.mark.parametrize("field", list(tomllib.loads(SDC_INPUT_TEMPLATE)))
def test_every_field_requires_a_string(tmp_path, field):
    values = tomllib.loads(SDC_INPUT_TEMPLATE)
    values[field] = 10
    path = tmp_path / "bad.tcl"
    path.write_text(tomli_w.dumps(values))
    with pytest.raises(ValueError, match="must be a string"):
        SdcInputs.from_file(path)
