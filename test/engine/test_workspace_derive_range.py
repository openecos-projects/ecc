"""A derived workspace's flow range keeps an inserted check with the step it checks."""

from types import SimpleNamespace
from typing import Any

import pytest

import chipcompiler.engine.workspace_derive_range as derive_range
from chipcompiler.data import Workspace
from chipcompiler.engine.workspace_lifecycle import WorkspaceLifecycleError
from test.flow_fixture import step_fields

_LEDGER = [
    ("Synthesis", "yosys"),
    ("CTS", "ecc"),
    ("lec@CTS", "kepler_formal"),
    ("legalization", "dreamplace"),
]


def _derived(tmp_path, monkeypatch) -> tuple[Any, Any]:
    workspace: Any = Workspace(directory=tmp_path)
    workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            {"name": name, "tool": tool, "state": "Success", **step_fields(name, tool)}
            for name, tool in _LEDGER
        ],
    }
    workspace.parameters.data["_flow"] = {"preset": "rtl2gds", "insert_steps": ["lec@CTS"]}
    flow = SimpleNamespace(
        workspace_steps=[], save=lambda: True, create_step_workspaces=lambda **_kwargs: None
    )
    monkeypatch.setattr(derive_range, "prepare_steps_for_rerun", lambda *_args: None)
    monkeypatch.setattr(derive_range, "save_parameter", lambda _parameters: True)
    return workspace, flow


def test_a_range_ending_at_a_step_keeps_its_inserted_check(tmp_path, monkeypatch):
    workspace, flow = _derived(tmp_path, monkeypatch)

    derive_range.bound_derived_flow(workspace, flow, "", "CTS")

    assert (
        [step["name"] for step in workspace.flow.data["steps"]],
        workspace.parameters.data["_flow"],
    ) == (
        ["Synthesis", "CTS", "lec@CTS"],
        {"start": "Synthesis", "end": "CTS", "insert_steps": ["lec@CTS"]},
    )


@pytest.mark.parametrize(
    ("from_step", "through_step"), [("lec@CTS", "legalization"), ("", "lec@CTS")]
)
def test_an_inserted_step_cannot_bound_the_range(tmp_path, monkeypatch, from_step, through_step):
    workspace, flow = _derived(tmp_path, monkeypatch)

    with pytest.raises(WorkspaceLifecycleError, match="lec@CTS is an inserted step"):
        derive_range.bound_derived_flow(workspace, flow, from_step, through_step)
