"""PDK overrides follow workspace-owned design inputs when persisted."""

import pytest

from chipcompiler.data import create_workspace, load_workspace


@pytest.mark.parametrize("field", ["sdc", "spef"])
def test_pdk_design_input_override_survives_source_removal(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters, field
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    rtl = tmp_path / "gcd.v"
    rtl.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    source = tmp_path / f"input.{field}"
    source.write_text("fixture\n")
    directory = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(directory),
        origin_def="",
        origin_verilog=str(rtl),
        pdk="ics55",
        pdk_root=str(pdk_root),
        parameters=default_ics55_parameters,
        pdk_overrides={field: str(source)},
    )
    source.unlink()

    loaded = load_workspace(str(directory))

    assert loaded.pdk == workspace.pdk
