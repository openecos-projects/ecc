"""synthesis_lec preset vs skip-policy interaction on `ecc run`.

The preset exists to run the synthesis LEC the default policy skips, so
a fresh creation needs an explicit `skip_steps = []` while an existing
ledger is never re-filtered.
"""

import json
import os

import pytest

from chipcompiler.cli import main as cli_main


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


def test_synthesis_lec_preset_conflict_never_fires_for_existing_ledger(
    tmp_path, create_cli_project, flow_mocks, set_flow_preset
):
    from chipcompiler.data.workspace_config import save_workspace_config

    project_dir = create_cli_project()
    set_flow_preset(project_dir, "synthesis_lec")
    run_dir = os.path.join(project_dir, "default")
    home = os.path.join(run_dir, "home")
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, "flow.json"), "w") as f:
        json.dump(
            {
                "steps": [
                    {"name": "Synthesis", "tool": "yosys", "state": "Success"},
                    {"name": "lec", "tool": "yosys_lec", "state": "Success"},
                ]
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
