"""Project format migration must not block a workspace's frozen timing inputs."""

import tomllib

import pytest
import tomli_w

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.command_handlers import project as project_commands
from chipcompiler.cli.core.types import CommandResult
from chipcompiler.cli.project.timing_template import SDC_INPUT_FILENAME
from chipcompiler.data import load_workspace, refresh_workspace_config
from chipcompiler.data.parameter import save_parameter
from chipcompiler.data.workspace.timing_constraints import generate_timing_scripts


@pytest.fixture(params=[False, True], ids=["toml-only", "manifest"])
def legacy_timing_project(request, tmp_path, minimal_ics55_pdk_factory, monkeypatch):
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

    frozen = {
        "clock_list": "clk MAX:100 WCL:100 MIN:100 ML:100 TYP:100\n",
        "generated_clock_txt": "# no derived clocks\n",
        "clk_group_txt": "# one clock domain\n",
        "io_constraint_txt": "set_input_delay 0.2 -clock CLK_clk [get_ports req]\n",
        "timing_exception_txt": "set_false_path -from [get_ports reset_n]\n",
    }
    workspace = load_workspace(project / "default")
    workspace.parameters.data["sdc"] = frozen
    assert save_parameter(workspace.parameters)
    refresh_workspace_config(workspace)
    generate_timing_scripts(workspace, has_io_cells=False)

    # The project may retain old input keys and no longer match the frozen run.
    document["design"].pop("sdc")
    document["design"].update(clock_port="clk", frequency_mhz=200.0)
    document.setdefault("params", {})["sdc"] = {
        **frozen,
        "clock_list": frozen["clock_list"].replace(":100", ":200"),
    }
    config.write_text(tomli_w.dumps(document))
    (project / SDC_INPUT_FILENAME).unlink()
    if not request.param:
        (project / "project.json").unlink()

    resumed = []

    def run_existing(command_input, ctx):
        loaded = load_workspace(ctx.run_dir)
        refresh_workspace_config(loaded)
        generate_timing_scripts(loaded, has_io_cells=False)
        resumed.append(loaded.parameters.data["sdc"])
        return CommandResult.ok([])

    monkeypatch.setattr(project_commands, "_run_workspace", run_existing)
    return project, frozen, resumed


def test_resume_uses_frozen_timing_despite_obsolete_project_keys(legacy_timing_project):
    project, frozen, resumed = legacy_timing_project
    origin = project / "default" / "origin"
    before = {path.relative_to(origin): path.read_bytes() for path in origin.glob("*CTS/*.tcl")}
    assert before

    assert cli_main.run(["run", "--project", str(project), "--resume"]) == 0

    assert resumed == [frozen]
    assert {
        path.relative_to(origin): path.read_bytes() for path in origin.glob("*CTS/*.tcl")
    } == before


@pytest.mark.parametrize("command", [["run", "--workspace", "fresh"], ["check"]])
def test_project_timing_validation_remains_strict(legacy_timing_project, command, capsys):
    project, _, resumed = legacy_timing_project
    capsys.readouterr()

    assert cli_main.run([*command, "--project", str(project)]) == 1

    assert "unknown parameter in ecc.toml: 'sdc.clock_list'" in capsys.readouterr().out
    assert resumed == []
    assert not (project / "fresh").exists()


@pytest.mark.parametrize(
    "section, values, message",
    [
        ("place", {"cell_padding_x": -1}, "place.cell_padding_x"),
        ("other", {"unknown": 1}, "unknown parameter in ecc.toml: 'other.unknown'"),
        ("sdc", {"typo": "ignored?"}, "unknown parameter in ecc.toml: 'sdc.typo'"),
        ("sdc", {"clock_list": 100}, "unknown parameter in ecc.toml: 'sdc.clock_list'"),
        ("sdc", "not a table", "[params.sdc] must be a table"),
    ],
)
def test_resume_still_rejects_invalid_parameters(
    legacy_timing_project, section, values, message, capsys
):
    project, _, resumed = legacy_timing_project
    config = project / "ecc.toml"
    document = tomllib.loads(config.read_text())
    if isinstance(values, dict):
        document["params"].setdefault(section, {}).update(values)
    else:
        document["params"][section] = values
    config.write_text(tomli_w.dumps(document))
    capsys.readouterr()

    assert cli_main.run(["run", "--project", str(project), "--resume"]) == 1

    assert message in capsys.readouterr().out
    assert resumed == []
