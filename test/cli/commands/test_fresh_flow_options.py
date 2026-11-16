"""A freshly built ledger carries the options projection (#424).

`EngineFlow.add_step` saves the ledger with its steps only. The fresh-run
path therefore writes the options projection once the ledger is complete;
otherwise the first workspace load, even from a query, rewrites flow.json.
"""

import json

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.data import load_workspace
from chipcompiler.engine import EngineFlow


class LedgerOnlyFlow(EngineFlow):
    """The real flow ledger, without step workspaces or tool execution."""

    def create_step_workspaces(self, **_kwargs):
        self.workspace_steps = list(self.workspace.flow.data.get("steps", []))

    def run_steps(self, **_kwargs):
        return True


@pytest.fixture
def fresh_project(tmp_path, monkeypatch, minimal_ics55_pdk_factory):
    """A project whose fresh runs build a real workspace and a real ledger."""
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", LedgerOnlyFlow)
    monkeypatch.setattr(
        "chipcompiler.rtl2gds.builder.build_rtl2gds_flow",
        lambda *, skip=(), lec_engine=None: [
            ("synthesis", "yosys", "Unstart"),
            ("pre_floorplan", "ecc", "Unstart"),
            ("placement", "dreamplace", "Unstart"),
        ],
    )
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root, overrides=None: None,
    )
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    pdk = minimal_ics55_pdk_factory(tmp_path / "pdk")
    (project / "rtl/gcd.v").write_text("module gcd(input clk); endmodule\n")
    config = project / "ecc.toml"
    config.write_text(config.read_text().replace('root = ""', f'root = "{pdk}"'))
    return project


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(["run", "--workspace", "fresh"], id="run"),
        pytest.param(["workspace", "create", "fresh"], id="workspace-create"),
    ],
)
def test_fresh_workspace_ledger_carries_the_options_projection(fresh_project, command):
    assert cli_main.run([*command, "--project", str(fresh_project)]) == 0

    # Read the file as the command left it: nothing has loaded the workspace yet.
    flow_json = fresh_project / "fresh" / "home" / "flow.json"
    persisted = flow_json.read_bytes()
    assert json.loads(persisted)["options"] == {"geometry": {"clock_tree": False}}

    assert load_workspace(fresh_project / "fresh") is not None
    assert flow_json.read_bytes() == persisted


def test_fresh_run_requests_one_persisted_projection(create_cli_project, flow_mocks):
    assert cli_main.run(["run", "--project", create_cli_project()]) == 0

    assert flow_mocks.capture["options_projections"] == [{"persist": True}]


@pytest.mark.parametrize("enabled", [False, True])
def test_workspace_cli_execution_persists_only_in_ledger(
    fresh_project, enabled, monkeypatch, capsys
):
    monkeypatch.delenv("ECC_STEP_SUBPROCESS", raising=False)
    config = fresh_project / "ecc.toml"
    before_config = config.read_bytes()
    flag = "--step-subprocess" if enabled else "--no-step-subprocess"
    assert (
        cli_main.run(["workspace", "create", "fresh", "--project", str(fresh_project), flag]) == 0
    )
    workspace = fresh_project / "fresh"
    flow_path = workspace / "home" / "flow.json"
    assert json.loads(flow_path.read_bytes())["options"]["execution"] == {
        "step_subprocess": enabled
    }
    params = workspace / "home" / "params.toml"
    before_params = params.read_bytes()
    assert b"step_subprocess" not in before_params
    capsys.readouterr()
    command = ["workspace", "execution", "fresh", "--project", str(fresh_project), "--plain"]
    assert cli_main.run(command) == 0
    output = capsys.readouterr().out
    assert f"step_subprocess={enabled}" in output
    assert "source=home/flow.json" in output
    opposite = "--no-step-subprocess" if enabled else "--step-subprocess"
    assert (
        cli_main.run(
            [*command, opposite, "--expected-revision", "1", "--command-id", "execution-1"]
        )
        == 0
    )
    before_retry = flow_path.read_bytes()
    assert (
        cli_main.run(
            [*command, opposite, "--expected-revision", "1", "--command-id", "execution-1"]
        )
        == 0
    )
    assert flow_path.read_bytes() == before_retry
    assert json.loads(before_retry)["options"]["execution"] == {"step_subprocess": not enabled}
    assert config.read_bytes() == before_config
    assert params.read_bytes() == before_params


def test_workspace_cli_execution_refuses_undeclared_target(fresh_project):
    assert (
        cli_main.run(
            [
                "workspace",
                "execution",
                "missing",
                "--project",
                str(fresh_project),
                "--no-step-subprocess",
            ]
        )
        != 0
    )
    assert not (fresh_project / "missing").exists()
