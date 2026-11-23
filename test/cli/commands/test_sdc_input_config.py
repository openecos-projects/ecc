"""External timing inputs reach frozen workspace inputs and generated scenarios."""

import json
import tomllib

import pytest
import tomli_w

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.project.timing_template import SDC_INPUT_FILENAME, SDC_INPUT_TEMPLATE
from chipcompiler.data import load_workspace, refresh_workspace_config
from chipcompiler.data.parameter import save_parameter
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


@pytest.mark.parametrize("custom", [False, True])
def test_toml_timing_inputs_survive_cli_creation_reload_and_refresh(
    tmp_path, flow_mocks, minimal_ics55_pdk_factory, custom
):
    project = tmp_path / "project"
    pdk = minimal_ics55_pdk_factory(tmp_path / "pdk")
    assert cli_main.run(["init", str(project), "--design-name", "gcd", "--pdk-root", str(pdk)]) == 0
    (project / "rtl/gcd.v").write_text("module gcd(input ref_clk); endmodule\n")
    config = project / "ecc.toml"
    text = config.read_text()
    values = {
        "clock_list": "ref_clk MAX:50 WCL:80 MIN:200 ML:125 TYP:83.25",
        "generated_clock_txt": "create_generated_clock -name CLK_div2 -divide_by 2 \\\n"
        "    -source [get_ports ref_clk] [get_pins u_div/Q]",
        "clk_group_txt": "# No asynchronous domains in this example\n",
        "io_constraint_txt": "set_input_delay 0.3 -max -clock CLK_ref_clk [get_ports req]\n",
        "timing_exception_txt": "set_false_path -from [get_ports reset_n]\n",
    }
    if custom:
        # Invalid clock syntax is ignored when a complete constraint file wins.
        values["clock_list"] = "not a clock declaration"
        text = text.replace("[design]", '[design]\nsdc = "constraints/full.tcl"')
        (project / "constraints/full.tcl").write_text(
            "# custom\ncreate_clock -period 8 [get_ports ref_clk]\n"
        )
    defaults = tomllib.loads(text)["params"]["sdc"]
    for key, value in values.items():
        text = text.replace(f"{key} = '''\n{defaults[key]}'''", f"{key} = '''\n{value}'''")
    config.write_text(text)
    assert tomllib.loads(text)["params"]["sdc"] == values

    assert cli_main.run(["run", "--project", str(project)]) == 0
    arguments = flow_mocks.capture["create_kwargs"]
    assert arguments["parameters"]["sdc"] == values
    if not custom:
        assert {key: arguments["parameters"][key] for key in ("clock", "frequency_max")} == {
            "clock": "ref_clk",
            "frequency_max": 83.25,
        }

    workspace = create_workspace(**{**arguments, "directory": tmp_path / "persisted"})
    assert workspace is not None
    loaded = load_workspace(workspace.directory)
    assert loaded.parameters.data["sdc"] == values
    generate_timing_scripts(loaded, has_io_cells=False)
    if custom:
        assert loaded.pdk.sdc is not None
        assert loaded.pdk.sdc.read_text() == (project / "constraints/full.tcl").read_text()
        assert set((loaded.directory / "origin").rglob("*.tcl")) == {
            loaded.pdk.sdc,
            loaded.directory / "origin/pre_CTS/full.tcl.ecc.tcl",
            loaded.directory / "origin/post_CTS/full.tcl.ecc.tcl",
        }
        return
    assert {key: loaded.parameters.data[key] for key in ("clock", "frequency_max")} == {
        "clock": "ref_clk",
        "frequency_max": 83.25,
    }
    frequencies = {"MAX": 50.0, "WCL": 80.0, "MIN": 200.0, "ML": 125.0, "TYP": 83.25}
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
        "set_input_delay 0.8 -max -clock CLK_ref_clk [get_ports req]"
    )
    assert save_parameter(loaded.parameters)
    refreshed = load_workspace(loaded.directory)
    refresh_workspace_config(refreshed)
    generate_timing_scripts(refreshed, has_io_cells=False)
    assert all(
        loaded.parameters.data["sdc"]["io_constraint_txt"] in path.read_text()
        for path in (refreshed.directory / "origin").rglob("*.tcl")
    )


@pytest.mark.parametrize("manifest", [False, True])
@pytest.mark.parametrize("legacy_metadata", [False, True])
def test_clock_list_is_the_source_of_primary_flow_metadata(
    tmp_path, flow_mocks, manifest, legacy_metadata
):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    if not manifest:
        (project / "project.json").unlink()
    else:
        manifest_path = project / "project.json"
        document = json.loads(manifest_path.read_text())
        document["base_design"]["frequency_mhz"] = "stale"
        manifest_path.write_text(json.dumps(document))
    (project / "rtl/gcd.v").write_text("module gcd(input bus_clk, input aux); endmodule\n")
    config = project / "ecc.toml"
    text = config.read_text().replace('root = ""', f'root = "{tmp_path}"')
    document = tomllib.loads(text)
    clocks = "bus_clk MAX:50 WCL:80 MIN:200 ML:125 TYP:83.25\naux MAX:25 WCL:25 MIN:25 ML:25 TYP:25"
    document["params"]["sdc"]["clock_list"] = clocks + "\n"
    if legacy_metadata:
        document["design"].update(clock_port="unused_clk", frequency_mhz=42.0)
    else:
        document["design"].pop("clock_port", None)
        document["design"].pop("frequency_mhz", None)
    config.write_text(tomli_w.dumps(document))

    assert cli_main.run(["run", "--project", str(project)]) == 0
    parameters = flow_mocks.capture["create_kwargs"]["parameters"]
    assert {key: parameters[key] for key in ("clock", "frequency_max")} == {
        "clock": "bus_clk",
        "frequency_max": 83.25,
    }
    assert parameters["sdc"]["clock_list"] == clocks + "\n"


@pytest.mark.parametrize(
    ("project_frequency", "cli_frequency", "frequency_max", "primary"),
    [
        # Only the list is replaced: its first row decides, in every corner.
        (None, None, 200.0, {"MAX": 180.0, "TYP": 200.0}),
        # An explicit design.frequency_mhz keeps its precedence over the row,
        # whether it comes with the list or was set in the project before.
        (None, "150", 150.0, {"MAX": 150.0, "TYP": 150.0}),
        ("150", None, 150.0, {"MAX": 150.0, "TYP": 150.0}),
    ],
)
def test_clock_list_replaced_with_set_supplies_the_primary_clock(
    tmp_path, flow_mocks, project_frequency, cli_frequency, frequency_max, primary
):
    from chipcompiler.data.workspace.sdc_inputs import PrimaryClock, SdcInputs

    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    (project / "rtl/gcd.v").write_text("module gcd(input clk, input core_clk); endmodule\n")
    config = project / "ecc.toml"
    config.write_text(config.read_text().replace('root = ""', f'root = "{tmp_path}"'))
    if project_frequency:
        command = ["param", "set", "design.frequency_mhz", project_frequency]
        assert cli_main.run([*command, "--project", str(project)]) == 0
    clocks = (
        "core_clk MAX:180 WCL:180 MIN:180 ML:180 TYP:200\nclk MAX:20 WCL:20 MIN:20 ML:20 TYP:25"
    )
    overrides = ["--set", f"sdc.clock_list={clocks}"]
    if cli_frequency:
        overrides += ["--set", f"design.frequency_mhz={cli_frequency}"]

    assert cli_main.run(["run", "--project", str(project), *overrides]) == 0

    parameters = flow_mocks.capture["create_kwargs"]["parameters"]
    assert {key: parameters[key] for key in ("clock", "frequency_max")} == {
        "clock": "core_clk",
        "frequency_max": frequency_max,
    }
    explicit = bool(project_frequency or cli_frequency)
    assert parameters.get("_explicit_frequency", False) is explicit
    inputs = SdcInputs.from_parameters(parameters)
    auxiliary = {"MAX": 20.0, "TYP": 25.0}
    for corner, frequency in primary.items():
        assert inputs.clocks(parameters, corner) == (
            PrimaryClock("core_clk", frequency),
            PrimaryClock("clk", auxiliary[corner]),
        )


def test_project_without_legacy_clock_metadata_requires_an_active_clock_list(
    tmp_path, flow_mocks, capsys
):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    (project / "rtl/gcd.v").write_text("module gcd(input clk); endmodule\n")
    config = project / "ecc.toml"
    text = config.read_text().replace('root = ""', f'root = "{tmp_path}"')
    document = tomllib.loads(text)
    document["params"]["sdc"]["clock_list"] = "# no clocks\n"
    document["design"].pop("clock_port", None)
    document["design"].pop("frequency_mhz", None)
    config.write_text(tomli_w.dumps(document))
    capsys.readouterr()

    assert cli_main.run(["run", "--project", str(project)]) == 1
    assert (
        "params.sdc.clock_list requires an uncommented primary-clock row" in capsys.readouterr().out
    )
    assert flow_mocks.capture["create_kwargs"] is None
