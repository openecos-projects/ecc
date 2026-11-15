import pytest

from chipcompiler.pdk.manifest import DescriptorError
from chipcompiler.tools.yosys.primitive_mapping import render_primitive_mapping


def test_mapping_accepts_arbitrary_master_and_pin_names(tmp_path):
    output = tmp_path / "mapping.v"
    render_primitive_mapping(
        [
            {
                "primitive": "$_DLATCH_P_",
                "instances": [
                    {"master": "vendor_latch", "pins": {"data": "D", "gate": "E", "out": "Q"}}
                ],
            }
        ],
        output,
    )
    assert "vendor_latch mapped_0 (.data(D), .gate(E), .out(Q));" in output.read_text()


@pytest.mark.parametrize("master", ["x; shell bad", "x\nendmodule", ""])
def test_mapping_rejects_code_injection(tmp_path, master):
    with pytest.raises(DescriptorError, match="invalid cell master"):
        render_primitive_mapping(
            [
                {
                    "primitive": "$_TBUF_",
                    "instances": [{"master": master, "pins": {"Y": "Y"}}],
                }
            ],
            tmp_path / "map.v",
        )
