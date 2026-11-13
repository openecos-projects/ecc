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
            ("Synthesis", "yosys", "Unstart"),
            ("place", "dreamplace", "Unstart"),
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
