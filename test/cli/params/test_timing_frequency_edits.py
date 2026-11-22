"""Real CLI mutations keep synthesis metadata and scenario clocks consistent."""

import tomllib

import pytest
import tomli_w

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.project.timing_template import SDC_INPUT_FILENAME
from chipcompiler.data import load_workspace, refresh_workspace_config
from chipcompiler.data.parameter import save_parameter
from chipcompiler.data.workspace.sdc_inputs import SdcInputs
from chipcompiler.data.workspace.timing_constraints import generate_timing_scripts


@pytest.fixture
def timing_project(tmp_path, minimal_ics55_pdk_factory):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    pdk = minimal_ics55_pdk_factory(tmp_path / "pdk")
    (project / "gcd.v").write_text("module gcd(input clk); endmodule\n")
    assert cli_main.run(["project", "set", "design.rtl", "gcd.v", "--project", str(project)]) == 0
    config = project / "ecc.toml"
    document = tomllib.loads(config.read_text())
    document["pdk"]["root"] = str(pdk)
    config.write_text(tomli_w.dumps(document))
    assert cli_main.run(["workspace", "create", "default", "--project", str(project)]) == 0
    workspace = load_workspace(project / "default")
    generate_timing_scripts(workspace, has_io_cells=False)
    return project


def _files(directory):
    """Capture persisted workspace state, excluding diagnostic logs."""
    return {
        path.relative_to(directory): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file() and path.relative_to(directory).parts[0] != "log"
    }


@pytest.mark.parametrize(
    "command",
    [
        ["set", "design.frequency_mhz", "200"],
        ["apply", "--set", "flow.run_analysis=false", "--set", "design.frequency_mhz=200"],
    ],
    ids=["single", "batch"],
)
def test_conflicting_frequency_edit_preserves_workspace_state(timing_project, command, capsys):
    project = timing_project
    directory = project / "default"
    before = _files(directory)
    inputs = SdcInputs.from_file(project / SDC_INPUT_FILENAME)
    # The workspace owns its frozen input, regardless of later project edits.
    (project / SDC_INPUT_FILENAME).write_text("no longer valid\n")
    capsys.readouterr()

    assert (
        cli_main.run(["param", *command, "--workspace", "default", "--project", str(project)]) == 1
    )

    output = capsys.readouterr().out
    assert "primary_clocks" in output
    assert "new workspace" in output
    assert _files(directory) == before
    loaded = load_workspace(directory)
    assert {key: loaded.parameters.data[key] for key in inputs.parameters()} == inputs.parameters()
    refresh_workspace_config(loaded)
    generate_timing_scripts(loaded, has_io_cells=False)
    assert _files(directory / "origin") == {
        path.relative_to("origin"): content
        for path, content in before.items()
        if path.parts[0] == "origin"
    }


@pytest.mark.parametrize("legacy", [False, True], ids=["literal", "legacy"])
def test_compatible_frequency_edits_keep_metadata_and_scenario_clocks_aligned(
    timing_project, legacy
):
    project = timing_project
    workspace = load_workspace(project / "default")
    original = SdcInputs.from_parameters(workspace.parameters.data)
    frequency = original.primary_clock().frequency_mhz
    if legacy:
        workspace.parameters.data["sdc"] = {
            "clock_list": "clk MAX:100 WCL:100 MIN:100 ML:100 TYP:100\n"
        }
        assert save_parameter(workspace.parameters)
        frequency = 200.0

    assert (
        cli_main.run(
            [
                "param",
                "set",
                "design.frequency_mhz",
                str(frequency),
                "--workspace",
                "default",
                "--project",
                str(project),
            ]
        )
        == 0
    )

    loaded = load_workspace(workspace.directory)
    refresh_workspace_config(loaded)
    generate_timing_scripts(loaded, has_io_cells=False)
    inputs = SdcInputs.from_parameters(loaded.parameters.data)
    assert (
        loaded.parameters.data["frequency_max"],
        inputs.clocks(loaded.parameters.data, "TYP")[0].frequency_mhz,
    ) == (frequency, frequency)
    for path in (loaded.directory / "origin").glob("*CTS/*.tcl"):
        if legacy:
            assert f"set clk_freq_mhz {frequency}" in path.read_text()
            assert f'lappend timing_clock_periods "CLK_clk" {1000 / frequency}' in path.read_text()
        else:
            assert original.primary_clocks in path.read_text()
