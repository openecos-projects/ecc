from pathlib import Path

import pytest

from chipcompiler.data import create_workspace, get_design_parameters, get_pdk
from chipcompiler.engine import EngineDB, EngineFlow

REPO_ROOT = Path(__file__).resolve().parents[2]


def gcd_fixture_verilog() -> Path:
    return REPO_ROOT / "test" / "fixtures" / "gcd" / "gcd.v"


def run_workspace_flow(
    flow_builder,
    *,
    design_name="gcd",
    pdk_name="ics55",
    workspace_suffix,
    pdk_root=None,
    with_engine_db=False,
):
    workspace_dir = REPO_ROOT / "test" / "examples" / workspace_suffix
    parameters = get_design_parameters(pdk_name, design_name)
    parameters.data["Design"] = design_name
    parameters.data["Top module"] = design_name
    parameters.data["Clock"] = "clk"

    if pdk_root is None:
        pdk = get_pdk(pdk_name=pdk_name)
    else:
        pdk = get_pdk(pdk_name, pdk_root=str(pdk_root))

    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(gcd_fixture_verilog()),
        pdk=pdk,
        parameters=parameters,
    )

    engine_db = EngineDB(workspace=workspace) if with_engine_db else None
    engine_flow = EngineFlow(workspace=workspace, engine_db=engine_db)
    if not engine_flow.has_init():
        for step, tool, state in flow_builder():
            engine_flow.add_step(step=step, tool=tool, state=state)

    engine_flow.create_step_workspaces()
    return engine_flow.run_steps()


@pytest.fixture
def run_workspace_flow_factory():
    return run_workspace_flow


@pytest.fixture
def gcd_fixture_verilog_path():
    return gcd_fixture_verilog()
