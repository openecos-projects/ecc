import json
import os
import shutil
import sys
from contextlib import suppress
from pathlib import Path

import pytest

from chipcompiler.data import create_workspace, get_design_parameters, get_pdk
from chipcompiler.engine import EngineDB, EngineFlow
from chipcompiler.utility.log import flush_cstdio

REPO_ROOT = Path(__file__).resolve().parents[2]


def gcd_fixture_verilog() -> Path:
    return REPO_ROOT / "test" / "fixtures" / "gcd" / "gcd.v"


def run_workspace_flow(
    flow_builder,
    *,
    workspace_base: Path,
    design_name="gcd",
    pdk_name="ics55",
    workspace_suffix,
    pdk_root=None,
    with_engine_db=False,
    emir_technology_file: Path | None = None,
):
    workspace_dir = workspace_base / workspace_suffix
    parameters = get_design_parameters(pdk_name, design_name)
    parameters.data["design"] = design_name
    parameters.data["top_module"] = design_name
    parameters.data["clock"] = "clk"
    if pdk_root is None:
        pdk = get_pdk(pdk_name=pdk_name)
    else:
        pdk = get_pdk(pdk_name, pdk_root=str(pdk_root))

    if emir_technology_file is not None and pdk.description:
        # Qualify synthetic EMIR only in a separate, explicitly labelled fixture
        # profile. Never mutate the user's installed/private PDK resources.
        from chipcompiler.pdk.manifest import Descriptor, resource_path

        descriptor = Descriptor.model_validate(pdk.description)
        fixture_root = workspace_base / f"{workspace_suffix}-test-pdk"
        fixture_root.mkdir()
        for resource in descriptor.resources.values():
            destination = fixture_root / resource.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                source = resource_path(pdk.require_root(), resource)
                try:
                    os.link(source, destination)
                except OSError:
                    shutil.copyfile(source, destination)
        shutil.copyfile(emir_technology_file, fixture_root / "synthetic-test-em.tech")
        description = descriptor.model_dump()
        description["profile_revision"] += "-synthetic-em-test-only"
        description["resources"]["test-em"] = {"path": "synthetic-test-em.tech", "role": "em"}
        (fixture_root / "ecc-pdk.json").write_text(json.dumps(description))
        pdk = get_pdk(pdk_name, fixture_root)
    elif emir_technology_file is not None:
        parameters.data["config_overrides"] = {
            "emir": {"technology_file_path": str(emir_technology_file)}
        }

    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(gcd_fixture_verilog()),
        pdk=pdk,
        parameters=parameters,
    )

    assert workspace is not None
    engine_db = EngineDB(workspace=workspace) if with_engine_db else None
    engine_flow = EngineFlow(workspace=workspace, engine_db=engine_db)
    if not engine_flow.has_init():
        for step, tool, state in flow_builder():
            engine_flow.add_step(step=step, tool=tool, state=state)

    engine_flow.create_step_workspaces()

    # EngineFlow.run_step dup2's fd 1/2 into each step's log file and never
    # restores them. Save/restore around the flow so pytest's own reporting
    # is not swallowed by the last step's log.
    saved_fds = (os.dup(1), os.dup(2))
    saved_streams = (sys.stdout, sys.stderr)
    try:
        return engine_flow.run_steps()
    finally:
        with suppress(Exception):
            sys.stdout.flush()
            sys.stderr.flush()
        flush_cstdio()
        os.dup2(saved_fds[0], 1)
        os.dup2(saved_fds[1], 2)
        os.close(saved_fds[0])
        os.close(saved_fds[1])
        sys.stdout, sys.stderr = saved_streams


@pytest.fixture
def run_workspace_flow_factory(tmp_path_factory):
    base = tmp_path_factory.mktemp("examples")

    def factory(flow_builder, **kwargs):
        return run_workspace_flow(flow_builder, workspace_base=base, **kwargs)

    return factory


@pytest.fixture
def gcd_fixture_verilog_path():
    return gcd_fixture_verilog()
