"""Sizer's stage rebuild commits the flow ledger before subflow.json."""

import json
from copy import deepcopy

from chipcompiler.data import OriginDesign, Workspace
from chipcompiler.data.schema_migrations import SCHEMA_VERSION_FIELD
from chipcompiler.data.workspace.flow_data import FLOW_JSON_SCHEMA_VERSION
from chipcompiler.tools.ecc_sizer import builder as sizer_builder
from chipcompiler.tools.ecc_sizer import subflow as sizer_subflow


def _workspace(tmp_path) -> Workspace:
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd", top_module="gcd"))
    workspace.flow.path = tmp_path / "home" / "flow.json"
    workspace.flow.path.parent.mkdir(parents=True)
    workspace.flow.data = {
        "steps": [
            {"name": "Timing optimization", "tool": "sizer", "state": "Success"},
            {"name": "route", "tool": "ecc", "state": "Success"},
        ]
    }
    return workspace


def _sizer_step(workspace):
    step = sizer_builder.build_step(
        workspace=workspace,
        step_name="Timing optimization",
        input_def="input.def",
        input_verilog="input.v",
    )
    sizer_builder.build_step_space(step)
    return step


def test_rebuild_persists_the_ledger_through_the_schema_writer(tmp_path):
    workspace = _workspace(tmp_path)
    step = _sizer_step(workspace)

    sizer_builder.build_sub_flow(workspace, step)

    on_disk = json.loads(workspace.flow.path.read_text())
    assert on_disk[SCHEMA_VERSION_FIELD] == FLOW_JSON_SCHEMA_VERSION
    assert [item["state"] for item in on_disk["steps"]] == ["Unstart", "Unstart"]
    assert step.subflow.path.is_file()


def test_failed_ledger_write_keeps_memory_and_disk_consistent(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    step = _sizer_step(workspace)
    before = deepcopy(workspace.flow.data)

    monkeypatch.setattr(sizer_subflow, "save_ledger", lambda _flow: False)
    sizer_builder.build_sub_flow(workspace, step)

    assert workspace.flow.data == before
    assert not workspace.flow.path.exists()
    assert not step.subflow.path.exists()
