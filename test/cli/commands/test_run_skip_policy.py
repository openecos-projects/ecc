"""Presets and the skip policy on `ecc run`."""

import json
import os

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.project.manifest import load_manifest


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
    markers = patch_all_flow_builders(monkeypatch)

    rc = cli_main.run(["run", "--project", project_dir])

    assert rc == 0
    assert flow_mocks.flow.instances[0].added_steps == markers[builder_attr]


@pytest.mark.parametrize("skip_steps", [None, [], ["diff_opt"]])
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
        if skip_steps == []
        else ["place", "diff_sizing", "CTS"]
    )
    assert names[place_index : cts_index + 1] == expected


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
    toml += '\nskip_steps = ["Synthesis"]\n'
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
