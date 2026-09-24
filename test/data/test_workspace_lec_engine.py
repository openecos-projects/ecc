"""LEC-engine config threading exercised through data.create_workspace.

Mirrors test_workspace_skip_policy.py: each test pins one ledger-level
lec_engine contract — validation before mutation, ledger seeding per
engine, normalized round-trip through params.toml, policy-only
persistence, and the explicit engine switch.
"""

import json
from copy import deepcopy

import pytest

from chipcompiler.data import create_workspace, load_workspace
from chipcompiler.utility import json_read


def _write_inputs(tmp_path):
    def_path = tmp_path / "gcd.def"
    def_path.write_text("VERSION 5.8 ;\nDESIGN gcd ;\nEND DESIGN\n")
    netlist_path = tmp_path / "gcd.v"
    netlist_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    return def_path, netlist_path


def test_create_workspace_rejects_invalid_lec_engine_before_any_mutation(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    _def_path, netlist_path = _write_inputs(tmp_path)

    workspace_dir = tmp_path / "workspace"
    with pytest.raises(ValueError, match="unknown LEC engine"):
        create_workspace(
            directory=workspace_dir,
            origin_def="",
            origin_verilog=netlist_path,
            pdk="ics55",
            parameters=deepcopy(default_ics55_parameters),
            pdk_root=pdk_root,
            flow_config={"start_step": "Synthesis", "end_step": "Harden", "lec_engine": "bogus"},
        )

    assert not workspace_dir.exists()


def test_create_workspace_seeds_the_declared_lec_engine(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    def_path, netlist_path = _write_inputs(tmp_path)

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=workspace_dir,
        origin_def=def_path,
        origin_verilog=netlist_path,
        pdk="ics55",
        parameters=deepcopy(default_ics55_parameters),
        pdk_root=pdk_root,
        flow_config={
            "start_step": "Synthesis",
            "end_step": "Harden",
            "skip_steps": [],
            "lec_engine": "yosys_lec",
        },
    )

    flow_data = json_read(workspace_dir / "home" / "flow.json")
    lec_entries = [
        (step["name"], step["tool"])
        for step in flow_data["steps"]
        if step["name"] in {"lec", "postRouteLec"}
    ]
    assert lec_entries == [("lec", "yosys_lec"), ("postRouteLec", "yosys_lec")]


def test_create_workspace_without_lec_engine_seeds_the_default(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    def_path, netlist_path = _write_inputs(tmp_path)

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=workspace_dir,
        origin_def=def_path,
        origin_verilog=netlist_path,
        pdk="ics55",
        parameters=deepcopy(default_ics55_parameters),
        pdk_root=pdk_root,
        flow_config={"start_step": "Synthesis", "end_step": "preFloorplan", "skip_steps": []},
    )

    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [(step["name"], step["tool"]) for step in flow_data["steps"]] == [
        ("Synthesis", "yosys"),
        ("lec", "kepler_formal"),
        ("preFloorplan", "ecc"),
    ]


def test_lec_engine_round_trips_through_params_toml_normalized(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    def_path, netlist_path = _write_inputs(tmp_path)

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=workspace_dir,
        origin_def=def_path,
        origin_verilog=netlist_path,
        pdk="ics55",
        parameters=deepcopy(default_ics55_parameters),
        pdk_root=pdk_root,
        flow_config={
            "start_step": "Synthesis",
            "end_step": "preFloorplan",
            "skip_steps": [],
            "lec_engine": "dual",
        },
    )

    # The alias is normalized to the member value at persistence; the alias
    # spelling never reaches params.toml.
    loaded = load_workspace(str(workspace_dir))
    flow_section = loaded.parameters.data["_flow"]
    assert flow_section["lec_engine"] == "lec_dual"

    from chipcompiler.data.workspace_config import load_workspace_config

    reloaded = load_workspace_config(workspace_dir)
    assert reloaded["_flow"]["lec_engine"] == "lec_dual"
    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert [step["tool"] for step in flow_data["steps"] if step["name"] == "lec"] == ["lec_dual"]


def test_create_workspace_policy_only_lec_engine_persists(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    """A policy-only flow config (no selected steps) still persists the
    declared engine, so ledger-less rebuilds resolve the same chain."""
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    _def_path, netlist_path = _write_inputs(tmp_path)

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=workspace_dir,
        origin_def="",
        origin_verilog=netlist_path,
        pdk="ics55",
        parameters=deepcopy(default_ics55_parameters),
        pdk_root=pdk_root,
        flow_config={"lec_engine": "yosys_lec"},
    )

    assert workspace is not None
    assert not (workspace_dir / "home" / "flow.json").exists()
    loaded = load_workspace(str(workspace_dir))
    assert loaded.parameters.data["_flow"] == {"lec_engine": "yosys_lec"}


def test_ledger_less_rebuild_uses_the_persisted_lec_engine(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    """build_flow_for_workspace without a ledger reads the persisted _flow
    for both the skip policy and the LEC engine."""
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    _def_path, netlist_path = _write_inputs(tmp_path)

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=workspace_dir,
        origin_def="",
        origin_verilog=netlist_path,
        pdk="ics55",
        parameters=deepcopy(default_ics55_parameters),
        pdk_root=pdk_root,
        flow_config={"lec_engine": "yosys_lec"},
    )

    loaded = load_workspace(str(workspace_dir))
    from chipcompiler.runtime.workspace_api import build_flow_for_workspace

    engine_flow = build_flow_for_workspace(loaded, create_step_workspaces=False)
    steps = engine_flow.workspace.flow.data["steps"]
    assert len(steps) > 0
    lec_entries = [
        (step["name"], step["tool"]) for step in steps if step["name"] in {"lec", "postRouteLec"}
    ]
    # The default policy skips the synthesis LEC; postRouteLec carries the
    # persisted engine.
    assert lec_entries == [("postRouteLec", "yosys_lec")]


def _create_lec_workspace(tmp_path, pdk_factory, parameters):
    pdk_root = pdk_factory(tmp_path / "ics55")
    def_path, netlist_path = _write_inputs(tmp_path)
    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=workspace_dir,
        origin_def=def_path,
        origin_verilog=netlist_path,
        pdk="ics55",
        parameters=deepcopy(parameters),
        pdk_root=pdk_root,
        flow_config={"start_step": "Synthesis", "end_step": "Harden", "skip_steps": []},
    )
    return workspace_dir


def _mark_lec_steps(workspace_dir, state):
    flow_path = workspace_dir / "home" / "flow.json"
    flow_data = json.loads(flow_path.read_text())
    for step in flow_data["steps"]:
        if step["name"] in {"lec", "postRouteLec"}:
            step["state"] = state
    flow_path.write_text(json.dumps(flow_data))


def test_switch_lec_engine_rewrites_ledger_and_persists_config(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    workspace_dir = _create_lec_workspace(
        tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
    )
    _mark_lec_steps(workspace_dir, "Success")
    loaded = load_workspace(str(workspace_dir))

    from chipcompiler.runtime.lec_engine_switch import switch_lec_engine

    switched = switch_lec_engine(loaded, "yosys_lec")

    assert switched == ("lec", "postRouteLec")
    flow_data = json_read(workspace_dir / "home" / "flow.json")
    steps = {step["name"]: step for step in flow_data["steps"]}
    assert steps["lec"]["tool"] == "yosys_lec"
    assert steps["postRouteLec"]["tool"] == "yosys_lec"
    assert steps["lec"]["state"] == "Unstart"
    assert steps["postRouteLec"]["state"] == "Unstart"
    # Unrelated step states are untouched.
    assert steps["Synthesis"]["state"] == "Unstart"
    assert steps["route"]["state"] == "Unstart"

    from chipcompiler.data.workspace_config import load_workspace_config

    assert load_workspace_config(workspace_dir)["_flow"]["lec_engine"] == "yosys_lec"

    # A rerun resolves evidence in the new engine's directory.
    from chipcompiler.data.step import flow_step_directory

    reloaded = load_workspace(str(workspace_dir))
    assert flow_step_directory(reloaded.flow.steps(), "lec") == "lec_yosys_lec"
    assert flow_step_directory(reloaded.flow.steps(), "postRouteLec") == ("postRouteLec_yosys_lec")


def test_switch_lec_engine_preserves_prior_engine_evidence(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    workspace_dir = _create_lec_workspace(
        tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
    )
    _mark_lec_steps(workspace_dir, "Success")

    # Prior-run evidence under the recorded engine.
    kepler_output = workspace_dir / "lec_kepler_formal" / "output"
    kepler_output.mkdir(parents=True)
    prior_result = kepler_output / "gcd_lec_result.json"
    prior_result.write_text('{"status": "proven"}\n')

    # Stale step state under the switch target engine.
    yosys_dir = workspace_dir / "lec_yosys_lec"
    yosys_dir.mkdir()
    subflow_path = yosys_dir / "subflow.json"
    subflow_path.write_text(
        json.dumps(
            {
                "path": str(subflow_path),
                "steps": [
                    {
                        "name": "run lec",
                        "state": "Success",
                        "runtime": "0:0:1",
                        "peak memory (mb)": 1,
                        "info": {},
                    }
                ],
            }
        )
    )
    checklist_path = yosys_dir / "checklist.json"
    checklist_path.write_text(json.dumps({"checklist": [{"id": "stale"}]}))

    loaded = load_workspace(str(workspace_dir))
    from chipcompiler.runtime.lec_engine_switch import switch_lec_engine

    switch_lec_engine(loaded, "yosys_lec")

    # The previous engine's directory is evidence: nothing is cleared.
    assert json.loads(prior_result.read_text()) == {"status": "proven"}
    # The target engine's stale subflow/checklist reset to the ledger state.
    subflow = json.loads(subflow_path.read_text())
    assert [step["state"] for step in subflow["steps"]] == ["Unstart"]
    assert json.loads(checklist_path.read_text())["checklist"] == []


def test_switch_lec_engine_rejects_an_unknown_engine(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    workspace_dir = _create_lec_workspace(
        tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
    )
    loaded = load_workspace(str(workspace_dir))

    from chipcompiler.runtime.lec_engine_switch import switch_lec_engine

    with pytest.raises(ValueError, match="unknown LEC engine"):
        switch_lec_engine(loaded, "bogus")

    flow_data = json_read(workspace_dir / "home" / "flow.json")
    assert {step["tool"] for step in flow_data["steps"] if step["name"] == "lec"} == {
        "kepler_formal"
    }
    from chipcompiler.data.workspace_config import load_workspace_config

    assert "lec_engine" not in load_workspace_config(workspace_dir)["_flow"]


def test_switch_lec_engine_config_save_failure_leaves_ledger_untouched(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters, monkeypatch
):
    workspace_dir = _create_lec_workspace(
        tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
    )
    _mark_lec_steps(workspace_dir, "Success")
    loaded = load_workspace(str(workspace_dir))

    import chipcompiler.runtime.lec_engine_switch as lec_engine_switch

    monkeypatch.setattr(lec_engine_switch, "_save_flow_parameters", lambda parameters: False)

    with pytest.raises(Exception, match="lec_engine"):
        lec_engine_switch.switch_lec_engine(loaded, "yosys_lec")

    # The ledger was never rewritten: tools and states are the pre-switch ones.
    flow_data = json_read(workspace_dir / "home" / "flow.json")
    steps = {step["name"]: step for step in flow_data["steps"]}
    assert steps["lec"]["tool"] == "kepler_formal"
    assert steps["lec"]["state"] == "Success"
    assert steps["postRouteLec"]["tool"] == "kepler_formal"
    assert "_flow" not in loaded.parameters.data or (
        "lec_engine" not in loaded.parameters.data["_flow"]
    )


def test_switch_lec_engine_ledger_save_failure_rolls_the_config_back(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters, monkeypatch
):
    workspace_dir = _create_lec_workspace(
        tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
    )
    _mark_lec_steps(workspace_dir, "Success")
    loaded = load_workspace(str(workspace_dir))

    from chipcompiler.engine.flow import EngineFlow
    from chipcompiler.runtime import lec_engine_switch

    monkeypatch.setattr(EngineFlow, "save", lambda self: False)

    with pytest.raises(Exception, match="flow ledger"):
        lec_engine_switch.switch_lec_engine(loaded, "yosys_lec")

    # The config was rolled back to the pre-switch section...
    from chipcompiler.data.workspace_config import load_workspace_config

    assert "lec_engine" not in load_workspace_config(workspace_dir)["_flow"]
    assert "lec_engine" not in loaded.parameters.data.get("_flow", {})
    # ...and the on-disk ledger keeps the pre-switch tools and states.
    flow_data = json_read(workspace_dir / "home" / "flow.json")
    steps = {step["name"]: step for step in flow_data["steps"]}
    assert steps["lec"]["tool"] == "kepler_formal"
    assert steps["lec"]["state"] == "Success"
