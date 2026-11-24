"""External timing inputs reach frozen workspace inputs and generated scenarios."""

import json
import tomllib

import pytest
import tomli_w

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.project.timing_template import SDC_INPUT_FILENAME, SDC_INPUT_TEMPLATE
from chipcompiler.data import load_workspace, refresh_workspace_config
from chipcompiler.data.workspace import create_workspace
from chipcompiler.data.workspace.sdc_inputs import SdcInputs
from chipcompiler.data.workspace.timing_constraints import generate_timing_scripts, timing_scenarios


def _timing_file(project, **overrides):
    values = tomllib.loads(SDC_INPUT_TEMPLATE)
    values.update(overrides)
    path = project / SDC_INPUT_FILENAME
    path.write_text(tomli_w.dumps(values))
    return path, values


def test_file_inputs_survive_cli_creation_reload_and_source_changes(
    tmp_path, flow_mocks, minimal_ics55_pdk_factory
):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    pdk = minimal_ics55_pdk_factory(tmp_path / "pdk")
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "gcd.v").write_text("module gcd(input ref_clk); endmodule\n")
    filelist = sources / "filelist.f"
    filelist.write_text("gcd.v\n")
    assert (
        cli_main.run(["project", "set", "design.rtl", str(filelist), "--project", str(project)])
        == 0
    )
    config = project / "ecc.toml"
    config.write_text(config.read_text().replace('root = ""', f'root = "{pdk}"'))
    source, values = _timing_file(
        project,
        primary_clocks="create_clock -name CLK_ref_clk -period 12.5 [get_ports ref_clk]\n",
        generated_clocks="create_generated_clock -name CLK_div2 -divide_by 2 \\\n"
        "    -source [get_ports ref_clk] [get_pins u_div/Q]",
        clock_groups="# No asynchronous domains in this example\n",
        io_constraints="set_input_delay 0.3 -max -clock CLK_ref_clk [get_ports req]\n",
        timing_exceptions="set_false_path -from [get_ports reset_n]\n",
    )
    original = source.read_bytes()
    timing_parameters = SdcInputs.from_file(source).parameters()
    assert "sdc" not in tomllib.loads(config.read_text()).get("params", {})
    assert cli_main.run(["run", "--project", str(project)]) == 0
    arguments = flow_mocks.capture["create_kwargs"]
    assert {key: arguments["parameters"][key] for key in ("clock", "frequency_max")} == {
        "clock": "ref_clk",
        "frequency_max": 80,
    }
    workspace = create_workspace(**{**arguments, "directory": tmp_path / "persisted"})
    assert workspace is not None
    assert {
        name: (workspace.directory / "origin" / name).read_bytes()
        for name in ("filelist.f", "gcd.v")
    } == {name: (sources / name).read_bytes() for name in ("filelist.f", "gcd.v")}
    snapshot = workspace.directory / "origin" / SDC_INPUT_FILENAME
    assert snapshot.read_bytes() == original

    # Existing workspaces own their snapshot; editing the project source is not live reload.
    source.write_text("not a valid timing file anymore\n")
    loaded = load_workspace(workspace.directory)
    refresh_workspace_config(loaded)
    generate_timing_scripts(loaded, has_io_cells=False)
    assert loaded.parameters.data["sdc"] == timing_parameters["sdc"]
    assert {key: loaded.parameters.data[key] for key in ("clock", "frequency_max")} == {
        "clock": "ref_clk",
        "frequency_max": 80,
    }
    for phase in ("pre_CTS", "post_CTS"):
        paths = list((loaded.directory / "origin" / phase).glob("*.tcl"))
        assert len(paths) == len(timing_scenarios(loaded))
        for path in paths:
            content = path.read_text()
            assert all(value in content for value in values.values())
            assert ("set_propagated_clock [all_clocks]" in content) == (phase == "post_CTS")
    assert snapshot.read_bytes() == original


@pytest.mark.parametrize("manifest", [False, True])
@pytest.mark.parametrize("legacy_metadata", [False, True])
def test_external_primary_clock_is_the_source_of_flow_metadata(
    tmp_path, flow_mocks, manifest, legacy_metadata
):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    assert cli_main.run(["project", "set", "design.rtl", "gcd.v", "--project", str(project)]) == 0
    if not manifest:
        (project / "project.json").unlink()
    else:
        manifest_path = project / "project.json"
        document = json.loads(manifest_path.read_text())
        document["base_design"]["frequency_mhz"] = "stale"
        manifest_path.write_text(json.dumps(document))
    (project / "gcd.v").write_text("module gcd(input bus_clk, input aux); endmodule\n")
    config = project / "ecc.toml"
    text = config.read_text().replace('root = ""', f'root = "{tmp_path}"')
    _timing_file(
        project,
        primary_clocks="create_clock -name BUS -period 12.5 [get_ports bus_clk]\n"
        "create_clock -name AUX -period 40 [get_ports aux]\n",
    )
    if legacy_metadata:
        text = text.replace("[design]", '[design]\nclock_port = "unused_clk"\nfrequency_mhz = 42.0')
    config.write_text(text)

    assert cli_main.run(["run", "--project", str(project)]) == 0
    parameters = flow_mocks.capture["create_kwargs"]["parameters"]
    assert {key: parameters[key] for key in ("clock", "frequency_max")} == {
        "clock": "bus_clk",
        "frequency_max": 80,
    }


@pytest.mark.parametrize(
    "contents, message",
    [
        ("create_clock -period 10 [get_ports clk]\n", "not a full SDC/Tcl script"),
        (
            tomli_w.dumps({**tomllib.loads(SDC_INPUT_TEMPLATE), "primary_clocks": "# no clocks\n"}),
            "primary_clocks requires an uncommented create_clock",
        ),
    ],
)
def test_invalid_timing_file_fails_before_workspace_creation(
    tmp_path, flow_mocks, capsys, contents, message
):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    (project / "gcd.v").write_text("module gcd(input clk); endmodule\n")
    assert cli_main.run(["project", "set", "design.rtl", "gcd.v", "--project", str(project)]) == 0
    config = project / "ecc.toml"
    config.write_text(config.read_text().replace('root = ""', f'root = "{tmp_path}"'))
    (project / SDC_INPUT_FILENAME).write_text(contents)
    capsys.readouterr()
    assert cli_main.run(["run", "--project", str(project)]) == 1
    assert message in capsys.readouterr().out
    assert flow_mocks.capture["create_kwargs"] is None


@pytest.mark.parametrize("remove_source", [False, True], ids=["changed", "removed"])
def test_existing_workspace_can_resume_without_valid_project_timing_source(
    tmp_path, minimal_ics55_pdk_factory, monkeypatch, remove_source
):
    from chipcompiler.cli.command_handlers import project as project_commands
    from chipcompiler.cli.core.types import CommandResult

    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    pdk = minimal_ics55_pdk_factory(tmp_path / "pdk")
    (project / "gcd.v").write_text("module gcd(input clk); endmodule\n")
    assert cli_main.run(["project", "set", "design.rtl", "gcd.v", "--project", str(project)]) == 0
    config = project / "ecc.toml"
    config.write_text(config.read_text().replace('root = ""', f'root = "{pdk}"'))
    assert cli_main.run(["workspace", "create", "default", "--project", str(project)]) == 0
    before = load_workspace(project / "default").parameters.data["sdc"]
    source = project / SDC_INPUT_FILENAME
    if remove_source:
        source.unlink()
    else:
        source.write_text("not a valid timing file anymore\n")
    resumed = []

    def run_existing(command_input, ctx):
        resumed.append(load_workspace(ctx.run_dir).parameters.data["sdc"])
        return CommandResult.ok([])

    monkeypatch.setattr(project_commands, "_run_workspace", run_existing)
    assert cli_main.run(["run", "--project", str(project), "--resume"]) == 0
    assert resumed == [before]


def test_grouped_timing_inputs_freeze_under_explicit_no_clock(
    tmp_path, flow_mocks, minimal_ics55_pdk_factory
):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    pdk = minimal_ics55_pdk_factory(tmp_path / "pdk")
    (project / "gcd.v").write_text("module gcd(input ref_clk); endmodule\n")
    assert cli_main.run(["project", "set", "design.rtl", "gcd.v", "--project", str(project)]) == 0
    config = project / "ecc.toml"
    config.write_text(
        config.read_text().replace('root = ""', f'root = "{pdk}"') + "no_clock = true\n"
    )
    _source, values = _timing_file(
        project,
        primary_clocks="create_clock -name CLK_ref_clk -period 12.5 [get_ports ref_clk]\n",
        generated_clocks="create_generated_clock -name CLK_div2 -divide_by 2 "
        "-source [get_ports ref_clk] [get_pins u_div/Q]\n",
        clock_groups="set_clock_groups -asynchronous -group {CLK_ref_clk} -group {CLK_div2}\n",
        io_constraints="set_input_delay 0.3 -max -clock CLK_ref_clk [get_ports req]\n",
        timing_exceptions="set_false_path -from [get_ports reset_n]\n",
    )

    assert cli_main.run(["run", "--project", str(project)]) == 0

    arguments = flow_mocks.capture["create_kwargs"]
    assert arguments["flow_config"]["no_clock"] is True
    assert {key: arguments["parameters"][key] for key in ("clock", "frequency_max")} == {
        "clock": "ref_clk",
        "frequency_max": 80,
    }
    workspace = create_workspace(**{**arguments, "directory": tmp_path / "persisted"})
    frozen = SdcInputs.from_parameters(workspace.parameters.data)
    assert frozen.primary_clocks == values["primary_clocks"]
    assert frozen.generated_clock_txt == values["generated_clocks"]
    assert frozen.clk_group_txt == values["clock_groups"]
    assert frozen.io_constraint_txt == values["io_constraints"]
    assert frozen.timing_exception_txt == values["timing_exceptions"]


def test_no_clock_does_not_relax_the_primary_clock_requirement(tmp_path, flow_mocks, capsys):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    (project / "gcd.v").write_text("module gcd(input clk); endmodule\n")
    assert cli_main.run(["project", "set", "design.rtl", "gcd.v", "--project", str(project)]) == 0
    config = project / "ecc.toml"
    config.write_text(
        config.read_text().replace('root = ""', f'root = "{tmp_path}"') + "no_clock = true\n"
    )
    _timing_file(project, primary_clocks="# generated clocks only\n")
    capsys.readouterr()

    assert cli_main.run(["run", "--project", str(project)]) == 1

    assert "primary_clocks requires an uncommented create_clock" in capsys.readouterr().out
    assert flow_mocks.capture["create_kwargs"] is None
