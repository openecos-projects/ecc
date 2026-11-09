"""synthesis_lec preset vs skip-policy interaction on `ecc run`.

The preset exists to run the synthesis LEC the default policy skips, so
a fresh creation needs an explicit `skip_steps = []` while an existing
ledger is never re-filtered.
"""

import json
import os

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.project.manifest import load_manifest
from test.flow_fixture import step_fields


def _enable_lec_in(project_dir):
    """Append an explicit empty skip list — the only LEC enable path."""
    toml_path = os.path.join(project_dir, "ecc.toml")
    with open(toml_path) as f:
        toml = f.read()
    toml += "\nskip_steps = []\n"
    with open(toml_path, "w") as f:
        f.write(toml)


@pytest.mark.parametrize(
    ("preset", "builder_attr"),
    [
        ("rtl2gds", "build_rtl2gds_flow"),
        ("syn_sta", "build_syn_sta_flow"),
        ("synthesis_lec", "build_synthesis_lec_flow"),
    ],
)
def test_run_dispatches_builder_for_preset(
    tmp_path,
    monkeypatch,
    create_cli_project,
    flow_mocks,
    set_flow_preset,
    patch_all_flow_builders,
    preset,
    builder_attr,
):
    project_dir = create_cli_project()
    set_flow_preset(project_dir, preset)
    if preset == "synthesis_lec":
        # The preset needs the synthesis LEC the default policy skips;
        # an explicit empty skip list is the only enable path.
        _enable_lec_in(project_dir)
    markers = patch_all_flow_builders(monkeypatch)

    rc = cli_main.run(["run", "--project", project_dir])

    assert rc == 0
    assert flow_mocks.flow.instances[0].added_steps == markers[builder_attr]


def test_synthesis_lec_preset_conflicts_with_default_skip_policy(
    tmp_path, capsys, create_cli_project, flow_mocks, set_flow_preset
):
    project_dir = create_cli_project()
    set_flow_preset(project_dir, "synthesis_lec")
    # No skip_steps declared: the code default skips lec.

    rc = cli_main.run(["run", "--project", project_dir])

    assert rc == 1
    assert "skip_steps = []" in capsys.readouterr().out
    assert flow_mocks.capture["create_kwargs"] is None


@pytest.mark.parametrize("skip_steps", [None, ["lec"], ["lec", "diff_opt"]])
def test_run_diff_opt_is_optional_and_keeps_diff_sizing(
    monkeypatch, create_cli_project, flow_mocks, skip_steps
):
    from chipcompiler.rtl2gds import build_rtl2gds_flow

    monkeypatch.setattr("chipcompiler.rtl2gds.builder.build_rtl2gds_flow", build_rtl2gds_flow)
    project_dir = create_cli_project()
    if skip_steps is not None:
        with open(os.path.join(project_dir, "ecc.toml"), "a") as config:
            config.write(f"\nskip_steps = {json.dumps(skip_steps)}\n")

    assert cli_main.run(["run", "--project", project_dir]) == 0

    names = [str(step) for step, _tool, _state in flow_mocks.flow.instances[0].added_steps]
    place_index = names.index("place")
    cts_index = names.index("CTS")
    expected = (
        ["place", "diff_opt", "diff_sizing", "CTS"]
        if skip_steps == ["lec"]
        else ["place", "diff_sizing", "CTS"]
    )
    assert names[place_index : cts_index + 1] == expected


def test_synthesis_lec_preset_conflict_never_fires_for_existing_ledger(
    tmp_path, create_cli_project, flow_mocks, set_flow_preset, monkeypatch
):
    from chipcompiler.data.workspace_config import save_workspace_config

    monkeypatch.setattr("chipcompiler.data.pdk.PDK.validate", lambda _self: None)
    project_dir = create_cli_project()
    set_flow_preset(project_dir, "synthesis_lec")
    run_dir = os.path.join(project_dir, "default")
    home = os.path.join(run_dir, "home")
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, "flow.json"), "w") as f:
        json.dump(
            {
                "schema_version": 2,
                "steps": [
                    {
                        "name": "Synthesis",
                        "tool": "yosys",
                        "state": "Success",
                        **step_fields("Synthesis", "yosys"),
                    },
                    {
                        "name": "lec",
                        "tool": "yosys_lec",
                        "state": "Success",
                        **step_fields("lec", "yosys_lec"),
                    },
                ],
            },
            f,
        )
    assert save_workspace_config(
        run_dir,
        {"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
        {"preset": "synthesis_lec"},
    )

    rc = cli_main.run(["run", "--project", project_dir, "--resume"])

    assert rc == 0


def test_run_skipping_synthesis_enters_with_the_declared_netlist(
    monkeypatch, create_cli_project, flow_mocks
):
    from chipcompiler.rtl2gds import build_rtl2gds_flow

    monkeypatch.setattr("chipcompiler.rtl2gds.builder.build_rtl2gds_flow", build_rtl2gds_flow)
    project_dir = create_cli_project()
    netlist = os.path.join(project_dir, "gcd_netlist.v")
    with open(netlist, "w") as f:
        f.write("module gcd(input clk); endmodule\n")
    toml_path = os.path.join(project_dir, "ecc.toml")
    with open(toml_path) as f:
        toml = f.read()
    toml = toml.replace("[design]\n", '[design]\nnetlist = "gcd_netlist.v"\n')
    toml += '\nskip_steps = ["Synthesis", "lec"]\n'
    with open(toml_path, "w") as f:
        f.write(toml)

    assert cli_main.run(["run", "--project", project_dir]) == 0

    create_kwargs = flow_mocks.capture["create_kwargs"]
    assert (create_kwargs["origin_verilog"], create_kwargs["parameters"]["_input_mode"]) == (
        netlist,
        "postSynthesis",
    )
    names = [str(step) for step, _tool, _state in flow_mocks.flow.instances[0].added_steps]
    assert names[0] == "preFloorplan"
    # project.json ranges the workspace from its entry step, so it reloads.
    (entry,) = load_manifest(project_dir).workspaces
    assert (entry.start_step, entry.end_step) == ("PreFloorplan", "Harden")
