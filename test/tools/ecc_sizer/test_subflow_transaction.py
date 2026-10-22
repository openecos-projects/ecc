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


def test_failed_ledger_write_keeps_existing_files_and_stages(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    step = _sizer_step(workspace)
    workspace.flow.path.write_text(json.dumps(workspace.flow.data, indent=2), encoding="utf-8")
    old_stages = {
        "path": str(step.subflow.path),
        "steps": [{"name": "old stage", "state": "Unstart"}],
    }
    step.subflow.path.write_text(json.dumps(old_stages), encoding="utf-8")
    before_ledger = json.loads(workspace.flow.path.read_text())
    before_subflow = json.loads(step.subflow.path.read_text())

    monkeypatch.setattr(sizer_subflow, "save_ledger", lambda _flow: False)
    sizer_builder.build_sub_flow(workspace, step)

    assert json.loads(workspace.flow.path.read_text()) == before_ledger
    assert workspace.flow.data == before_ledger
    assert json.loads(step.subflow.path.read_text()) == before_subflow
    assert step.subflow.steps == before_subflow["steps"]


def test_failed_subflow_write_keeps_the_committed_ledger_reset(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    step = _sizer_step(workspace)

    monkeypatch.setattr(sizer_subflow.SizerSubFlow, "save", lambda self: False)
    sizer_builder.build_sub_flow(workspace, step)

    on_disk = json.loads(workspace.flow.path.read_text())
    assert [item["state"] for item in on_disk["steps"]] == ["Unstart", "Unstart"]
