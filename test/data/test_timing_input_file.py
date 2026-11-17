"""The user-file boundary accepts structured timing data, not executable SDC."""

import tomllib

import pytest
import tomli_w

from chipcompiler.cli.project.timing_template import SDC_INPUT_TEMPLATE
from chipcompiler.data.workspace.sdc_inputs import SdcInputs


def test_file_round_trip_preserves_all_groups_and_derives_clock_metadata(tmp_path):
    values = tomllib.loads(SDC_INPUT_TEMPLATE)
    values.update(
        clock_list="ref_clk TYP:12.288 MIN:25\nu_pll/Q TYP:200 MIN:250",
        generated_clock_txt="create_generated_clock -name div2 -divide_by 2 \\\n"
        "    -source [get_ports ref_clk] [get_pins u_div/Q]\n",
        clk_group_txt="# same clock domain\n",
        io_constraint_txt="set_input_delay 0.3 -clock CLK_ref_clk [get_ports {req[0]}]\n",
        timing_exception_txt="set_false_path -from [get_ports test_mode]\n",
    )
    path = tmp_path / "design.tcl"
    content = tomli_w.dumps(values)
    path.write_text(content)
    inputs = SdcInputs.from_file(path)
    assert inputs == SdcInputs(**values)
    assert inputs.parameters() == {"sdc": values, "clock": "ref_clk", "frequency_max": 12.288}
    assert path.read_text() == content


@pytest.mark.parametrize(
    "content, message",
    [
        ("create_clock -period 10 [get_ports clk]\n", "not a full SDC/Tcl script"),
        ("clock_list = '''unterminated", "expected five TOML string fields"),
        ("[params.sdc]\n" + SDC_INPUT_TEMPLATE, "five fields at the file root"),
        (SDC_INPUT_TEMPLATE + "unexpected = 'value'\n", "unknown="),
        ("clock_list = 'clk TYP:100'\n", "missing="),
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
