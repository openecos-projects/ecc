"""A freshly built ledger carries the options projection (#424).

`EngineFlow.add_step` saves the ledger with its steps only. The fresh-run
path therefore writes the options projection once the ledger is complete;
otherwise the first workspace load, even from a query, rewrites flow.json.
"""

import json

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.data import load_workspace


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
