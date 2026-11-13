"""A freshly built ledger carries the options projection (#424).

`EngineFlow.add_step` saves the ledger with its steps only. The fresh-run
path therefore writes the options projection once the ledger is complete;
otherwise the first workspace load, even from a query, rewrites flow.json.
"""

import json

from chipcompiler.cli import main as cli_main
from chipcompiler.data import load_workspace
from chipcompiler.data.workspace import create_workspace
from chipcompiler.data.workspace.flow_options import sync_flow_options_projection
from chipcompiler.engine.flow import EngineFlow


def _fresh_workspace(tmp_path, flow_mocks, minimal_ics55_pdk_factory):
    """A real workspace built from the arguments `ecc run` hands to the engine."""
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    pdk = minimal_ics55_pdk_factory(tmp_path / "pdk")
    (project / "rtl/gcd.v").write_text("module gcd(input clk); endmodule\n")
    config = project / "ecc.toml"
    config.write_text(config.read_text().replace('root = ""', f'root = "{pdk}"'))
    assert cli_main.run(["run", "--project", str(project)]) == 0
    arguments = flow_mocks.capture["create_kwargs"]
    workspace = create_workspace(**{**arguments, "directory": tmp_path / "persisted"})
    assert workspace is not None
    engine_flow = EngineFlow(workspace=workspace)
    engine_flow.add_step(step="Synthesis", tool="yosys", state="Unstart")
    engine_flow.add_step(step="place", tool="dreamplace", state="Unstart")
    return workspace


def test_ledger_built_step_by_step_has_no_options_until_projected(
    tmp_path, flow_mocks, minimal_ics55_pdk_factory
):
    workspace = _fresh_workspace(tmp_path, flow_mocks, minimal_ics55_pdk_factory)
    flow_json = workspace.directory / "home" / "flow.json"
    assert "options" not in json.loads(flow_json.read_text())

    assert sync_flow_options_projection(workspace, persist=True) is True

    assert json.loads(flow_json.read_text())["options"] == {"geometry": {"clock_tree": False}}


def test_loading_a_projected_ledger_does_not_rewrite_it(
    tmp_path, flow_mocks, minimal_ics55_pdk_factory
):
    workspace = _fresh_workspace(tmp_path, flow_mocks, minimal_ics55_pdk_factory)
    sync_flow_options_projection(workspace, persist=True)
    flow_json = workspace.directory / "home" / "flow.json"
    projected = flow_json.read_bytes()

    assert load_workspace(workspace.directory) is not None

    assert flow_json.read_bytes() == projected
