"""External timing inputs reach frozen workspace inputs and generated scenarios."""

import json
import tomllib

import pytest
import tomli_w

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.project.timing_template import SDC_INPUT_TEMPLATE
from chipcompiler.data import load_workspace, refresh_workspace_config
from chipcompiler.data.workspace import create_workspace
from chipcompiler.data.workspace.timing_constraints import generate_timing_scripts, timing_scenarios


def _timing_file(project, **overrides):
    values = tomllib.loads(SDC_INPUT_TEMPLATE)
    values.update(overrides)
    path = project / "sdc/gcd.tcl"
    path.write_text(tomli_w.dumps(values))
    return path, values


def test_file_inputs_survive_cli_creation_reload_and_source_changes(
    tmp_path, flow_mocks, minimal_ics55_pdk_factory
):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    pdk = minimal_ics55_pdk_factory(tmp_path / "pdk")
    (project / "rtl/gcd.v").write_text("module gcd(input ref_clk); endmodule\n")
    config = project / "ecc.toml"
    config.write_text(config.read_text().replace('root = ""', f'root = "{pdk}"'))
    source, values = _timing_file(
        project,
        clock_list="ref_clk MAX:50 WCL:80 MIN:200 ML:125 TYP:83.25",
        generated_clock_txt="create_generated_clock -name CLK_div2 -divide_by 2 \\\n"
        "    -source [get_ports ref_clk] [get_pins u_div/Q]",
        clk_group_txt="# No asynchronous domains in this example\n",
        io_constraint_txt="set_input_delay 0.3 -max -clock CLK_ref_clk [get_ports req]\n",
        timing_exception_txt="set_false_path -from [get_ports reset_n]\n",
    )
    original = source.read_bytes()
    assert "sdc" not in tomllib.loads(config.read_text()).get("params", {})
    assert cli_main.run(["run", "--project", str(project)]) == 0
    arguments = flow_mocks.capture["create_kwargs"]
    assert {key: arguments["parameters"][key] for key in ("clock", "frequency_max")} == {
        "clock": "ref_clk",
        "frequency_max": 83.25,
    }
    workspace = create_workspace(**{**arguments, "directory": tmp_path / "persisted"})
    assert workspace is not None
    snapshot = workspace.directory / "origin/gcd.tcl"
    assert snapshot.read_bytes() == original

    # Existing workspaces own their snapshot; editing the project source is not live reload.
    source.write_text("not a valid timing file anymore\n")
    loaded = load_workspace(workspace.directory)
    refresh_workspace_config(loaded)
    generate_timing_scripts(loaded, has_io_cells=False)
    assert loaded.parameters.data["sdc"] == values
    assert {key: loaded.parameters.data[key] for key in ("clock", "frequency_max")} == {
        "clock": "ref_clk",
        "frequency_max": 83.25,
    }
    frequencies = {"MAX": 50.0, "WCL": 80.0, "MIN": 200.0, "ML": 125.0, "TYP": 83.25}
    for phase in ("pre_CTS", "post_CTS"):
        paths = list((loaded.directory / "origin" / phase).glob("*.tcl"))
        assert len(paths) == len(timing_scenarios(loaded))
        for path in paths:
            content = path.read_text()
            corner = path.stem.split("_", 1)[0]
            assert f"set clk_freq_mhz {frequencies[corner]}" in content
            assert all(value in content for key, value in values.items() if key != "clock_list")
            assert ("set_propagated_clock [all_clocks]" in content) == (phase == "post_CTS")
    assert snapshot.read_bytes() == original


@pytest.mark.parametrize("manifest", [False, True])
@pytest.mark.parametrize("legacy_metadata", [False, True])
def test_external_clock_list_is_the_source_of_primary_flow_metadata(
    tmp_path, flow_mocks, manifest, legacy_metadata
):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    if not manifest:
        (project / "project.json").unlink()
    else:
        manifest_path = project / "project.json"
        document = json.loads(manifest_path.read_text())
        document["base_design"]["parameters"]["frequency_max"] = "stale"
        manifest_path.write_text(json.dumps(document))
    (project / "rtl/gcd.v").write_text("module gcd(input bus_clk, input aux); endmodule\n")
    config = project / "ecc.toml"
    text = config.read_text().replace('root = ""', f'root = "{tmp_path}"')
    _timing_file(
        project,
        clock_list="bus_clk MAX:50 WCL:80 MIN:200 ML:125 TYP:83.25\n"
        "aux MAX:25 WCL:25 MIN:25 ML:25 TYP:25",
    )
    if legacy_metadata:
        text = text.replace("[design]", '[design]\nclock_port = "unused_clk"\nfrequency_mhz = 42.0')
    config.write_text(text)

    assert cli_main.run(["run", "--project", str(project)]) == 0
    parameters = flow_mocks.capture["create_kwargs"]["parameters"]
    assert {key: parameters[key] for key in ("clock", "frequency_max")} == {
        "clock": "bus_clk",
        "frequency_max": 83.25,
    }


@pytest.mark.parametrize(
    "contents, message",
    [
        ("create_clock -period 10 [get_ports clk]\n", "not a full SDC/Tcl script"),
        (
            tomli_w.dumps({**tomllib.loads(SDC_INPUT_TEMPLATE), "clock_list": "# no clocks\n"}),
            "clock_list requires an uncommented primary-clock row",
        ),
    ],
)
def test_invalid_timing_file_fails_before_workspace_creation(
    tmp_path, flow_mocks, capsys, contents, message
):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    (project / "rtl/gcd.v").write_text("module gcd(input clk); endmodule\n")
    config = project / "ecc.toml"
    config.write_text(config.read_text().replace('root = ""', f'root = "{tmp_path}"'))
    (project / "sdc/gcd.tcl").write_text(contents)
    capsys.readouterr()
    assert cli_main.run(["run", "--project", str(project)]) == 1
    assert message in capsys.readouterr().out
    assert flow_mocks.capture["create_kwargs"] is None


def test_existing_workspace_can_resume_after_project_timing_source_is_removed(
    tmp_path, minimal_ics55_pdk_factory, monkeypatch
):
    from chipcompiler.cli.command_handlers import project as project_commands
    from chipcompiler.cli.core.types import CommandResult

    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    pdk = minimal_ics55_pdk_factory(tmp_path / "pdk")
    (project / "rtl/gcd.v").write_text("module gcd(input clk); endmodule\n")
    config = project / "ecc.toml"
    config.write_text(config.read_text().replace('root = ""', f'root = "{pdk}"'))
    assert cli_main.run(["workspace", "create", "default", "--project", str(project)]) == 0
    before = load_workspace(project / "default").parameters.data["sdc"]
    (project / "sdc/gcd.tcl").unlink()
    resumed = []

    def run_existing(command_input, ctx):
        resumed.append(load_workspace(ctx.run_dir).parameters.data["sdc"])
        return CommandResult.ok([])

    monkeypatch.setattr(project_commands, "_run_workspace", run_existing)
    assert cli_main.run(["run", "--project", str(project), "--resume"]) == 0
    assert resumed == [before]
