"""The ledger round trip is the persisted-format contract for the step enums.

`flow.json` is the only ledger format; writing and reading it must not change
any step, tool, state or category value when the members are `StrEnum`.
"""

import copy
import json

import pytest

from chipcompiler.data import OriginDesign, Workspace
from chipcompiler.data.step.results import results_digest
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.rtl2gds import build_flow_range
from test.flow_fixture import step_fields


def test_flow_ledger_round_trip_preserves_every_value(tmp_path):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd", top_module="gcd"))
    flow_path = tmp_path / "home" / "flow.json"
    flow_path.parent.mkdir(parents=True)
    workspace.flow.path = flow_path
    flow = EngineFlow(workspace)
    flow.workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            flow.init_flow_step(step, tool, state)
            for step, tool, state in build_flow_range("Synthesis", "Harden")
        ],
    }
    before_steps = copy.deepcopy(flow.workspace.flow.data.get("steps", []))

    assert flow.save()

    on_disk = json.loads(flow_path.read_text(encoding="utf-8"))
    reloaded = EngineFlow(workspace)
    assert on_disk["steps"] == before_steps
    assert reloaded.workspace.flow.data.get("steps", []) == before_steps
    for step in reloaded.workspace.flow.data.get("steps", []):
        for key in ("name", "tool", "state", "category"):
            assert type(step.get(key)) is str


def test_flow_document_round_trip_preserves_unknown_fields(tmp_path):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd", top_module="gcd"))
    flow_path = tmp_path / "home" / "flow.json"
    flow_path.parent.mkdir(parents=True)
    document = {
        "schema_version": 2,
        "steps": [
            {
                "name": "route",
                "tool": "ecc",
                "state": "Unstart",
                "category": "PNR",
                "directory": "12_route_ecc",
                "future_step_field": {"nested": [1, 2]},
            }
        ],
        "future_document_field": "kept",
    }
    flow_path.write_text(json.dumps(document), encoding="utf-8")
    workspace.flow.path = flow_path
    flow = EngineFlow(workspace)

    assert flow.load() is True
    assert flow.workspace.flow.data == document
    assert flow.save()
    # Saving stamps the digest of the step results the ledger was generated from.
    assert json.loads(flow_path.read_text(encoding="utf-8")) == {
        **document,
        "step_results_digest": results_digest(document["steps"]),
    }


def test_non_list_steps_are_rejected_without_rewriting_the_document(tmp_path):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd"))
    flow_path = tmp_path / "home" / "flow.json"
    flow_path.parent.mkdir(parents=True)
    document = {"schema_version": 2, "steps": {"name": "route"}}
    flow_path.write_text(json.dumps(document), encoding="utf-8")
    workspace.flow.path = flow_path

    with pytest.raises(ValueError, match="steps must be a list"):
        EngineFlow(workspace)
    assert json.loads(flow_path.read_text(encoding="utf-8")) == document


def test_state_less_entry_is_rejected(tmp_path):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd"))
    flow_path = tmp_path / "home" / "flow.json"
    flow_path.parent.mkdir(parents=True)
    document = {
        "schema_version": 2,
        "steps": [{"name": "route", "tool": "ecc", **step_fields("route", "ecc")}],
    }
    flow_path.write_text(json.dumps(document), encoding="utf-8")
    workspace.flow.path = flow_path

    with pytest.raises(ValueError, match="missing state"):
        EngineFlow(workspace)
