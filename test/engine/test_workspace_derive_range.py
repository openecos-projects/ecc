"""A derived workspace's flow range keeps an inserted check with the step it checks."""

from types import SimpleNamespace
from typing import Any

import pytest
from test.flow_fixture import step_fields

import chipcompiler.engine.workspace.derive_range as derive_range
from chipcompiler.data import Workspace
from chipcompiler.engine.workspace.lifecycle import WorkspaceLifecycleError

_LEDGER = [
    ("synthesis", "yosys"),
    ("cts", "ecc"),
    ("lec@cts", "kepler_formal"),
    ("legalization", "dreamplace"),
]


def _derived(tmp_path, monkeypatch, *, ledger=_LEDGER, flow_policy=None) -> tuple[Any, Any]:
    workspace: Any = Workspace(directory=tmp_path)
    workspace.flow.data = {
        "schema_version": 3,
        "steps": [
            {"name": name, "tool": tool, "state": "Success", **step_fields(name, tool)}
            for name, tool in ledger
        ],
    }
    workspace.parameters.data["_flow"] = flow_policy or {
        "preset": "rtl2gds",
        "insert_steps": ["lec@cts"],
    }
    flow = SimpleNamespace(
        workspace_steps=[], save=lambda: True, create_step_workspaces=lambda **_kwargs: None
    )
    monkeypatch.setattr(derive_range, "prepare_steps_for_rerun", lambda *_args: None)
    monkeypatch.setattr(derive_range, "save_parameter", lambda _parameters: True)
    return workspace, flow


def test_a_range_ending_at_a_step_keeps_its_inserted_check(tmp_path, monkeypatch):
    workspace, flow = _derived(tmp_path, monkeypatch)

    derive_range.bound_derived_flow(workspace, flow, "", "cts")

    assert (
        [step["name"] for step in workspace.flow.data["steps"]],
        workspace.parameters.data["_flow"],
    ) == (
        ["synthesis", "cts", "lec@cts"],
        {"start": "synthesis", "end": "cts", "insert_steps": ["lec@cts"]},
    )


def test_a_derived_range_keeps_the_effective_no_clock_policy(tmp_path, monkeypatch):
    no_clock_skips = ["preplace", "diff_opt", "diff_sizing", "cts", "timing_optimization"]
    workspace, flow = _derived(
        tmp_path,
        monkeypatch,
        ledger=[
            ("synthesis", "yosys"),
            ("placement", "dreamplace"),
            ("legalization", "dreamplace"),
        ],
        flow_policy={
            "preset": "rtl2gds",
            "no_clock": True,
            "skip_steps": no_clock_skips,
        },
    )

    derive_range.bound_derived_flow(workspace, flow, "", "legalization")

    assert (
        [step["name"] for step in workspace.flow.data["steps"]],
        workspace.parameters.data["_flow"],
    ) == (
        ["synthesis", "placement", "legalization"],
        {
            "start": "synthesis",
            "end": "legalization",
            "no_clock": True,
            "skip_steps": no_clock_skips,
        },
    )


@pytest.mark.parametrize(
    ("from_step", "through_step"), [("lec@cts", "legalization"), ("", "lec@cts")]
)
def test_an_inserted_step_cannot_bound_the_range(tmp_path, monkeypatch, from_step, through_step):
    workspace, flow = _derived(tmp_path, monkeypatch)

    with pytest.raises(WorkspaceLifecycleError, match="lec@cts is an inserted step"):
        derive_range.bound_derived_flow(workspace, flow, from_step, through_step)
