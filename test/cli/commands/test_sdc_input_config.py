"""The editable project template reaches persisted workspace timing scenarios."""

import tomllib

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.data import load_workspace, refresh_workspace_config
from chipcompiler.data.parameter import save_parameter
from chipcompiler.data.workspace import create_workspace
from chipcompiler.data.workspace.timing_constraints import generate_timing_scripts, timing_scenarios


@pytest.mark.parametrize("custom", [False, True])
def test_toml_timing_inputs_survive_cli_creation_reload_and_refresh(
    tmp_path, flow_mocks, minimal_ics55_pdk_factory, custom
):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    pdk = minimal_ics55_pdk_factory(tmp_path / "pdk")
    (project / "rtl/gcd.v").write_text("module gcd(input clk); endmodule\n")
    config = project / "ecc.toml"
    text = config.read_text().replace('root = ""', f'root = "{pdk}"')
    values = {
        "clock_list": "clk MAX:50 WCL:80 MIN:200 ML:125 TYP:100",
        "generated_clock_txt": "create_generated_clock -name CLK_div2 -divide_by 2 \\\n"
        "    -source [get_ports clk] [get_pins u_div/Q]",
        "clk_group_txt": "# No asynchronous domains in this example\n",
        "io_constraint_txt": "set_input_delay 0.3 -max -clock CLK_clk [get_ports req]\n",
        "timing_exception_txt": "set_false_path -from [get_ports reset_n]\n",
    }
    if custom:
        # Invalid clock syntax is ignored when a complete constraint file wins.
        values["clock_list"] = "not a clock declaration"
        text = text.replace('# sdc = "constraints/constraints.tcl"', 'sdc = "constraints/full.tcl"')
        (project / "constraints/full.tcl").write_text(
            "# custom\ncreate_clock -period 8 [get_ports clk]\n"
        )
    defaults = tomllib.loads(text)["params"]["sdc"]
    for key, value in values.items():
        text = text.replace(f"{key} = '''\n{defaults[key]}'''", f"{key} = '''\n{value}'''")
    config.write_text(text)
    assert tomllib.loads(text)["params"]["sdc"] == values

    assert cli_main.run(["run", "--project", str(project)]) == 0
    arguments = flow_mocks.capture["create_kwargs"]
    assert arguments["parameters"]["sdc"] == values

    workspace = create_workspace(**{**arguments, "directory": tmp_path / "persisted"})
    assert workspace is not None
    loaded = load_workspace(workspace.directory)
    assert loaded.parameters.data["sdc"] == values
    generate_timing_scripts(loaded, has_io_cells=False)
    if custom:
        assert loaded.pdk.sdc is not None
        assert loaded.pdk.sdc.read_text() == (project / "constraints/full.tcl").read_text()
        assert not (loaded.directory / "origin/pre_CTS").exists()
        return
    frequencies = {"MAX": 50.0, "WCL": 80.0, "MIN": 200.0, "ML": 125.0, "TYP": 100.0}
    assert len(list((loaded.directory / "origin").rglob("*.tcl"))) == 2 * len(
        timing_scenarios(loaded)
    )
    for phase in ("pre_CTS", "post_CTS"):
        for path in (loaded.directory / "origin" / phase).glob("*.tcl"):
            content = path.read_text()
            corner = path.stem.split("_", 1)[0]
            assert f"set clk_freq_mhz {frequencies[corner]}" in content
            assert all(value in content for key, value in values.items() if key != "clock_list")
            assert ("set_propagated_clock [all_clocks]" in content) == (phase == "post_CTS")
    loaded.parameters.data["sdc"]["io_constraint_txt"] = (
        "set_input_delay 0.8 -max -clock CLK_clk [get_ports req]"
    )
    assert save_parameter(loaded.parameters)
    refreshed = load_workspace(loaded.directory)
    refresh_workspace_config(refreshed)
    generate_timing_scripts(refreshed, has_io_cells=False)
    assert all(
        loaded.parameters.data["sdc"]["io_constraint_txt"] in path.read_text()
        for path in (refreshed.directory / "origin").rglob("*.tcl")
    )
