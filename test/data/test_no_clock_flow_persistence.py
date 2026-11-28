"""No-clock flow persistence, ledger construction, and range boundaries."""

from copy import deepcopy

import pytest

from chipcompiler.data.flow.build import build_dynamic_flow_data
from chipcompiler.data.workspace.config import (
    WorkspaceFlowTargetError,
    flow_section_from_flow_config,
    load_workspace_config,
    save_workspace_config,
    validate_flow_config,
)
from chipcompiler.rtl2gds import resolve_skip_steps

_NO_CLOCK_SKIPS = ("preplace", "diff_opt", "diff_sizing", "cts", "timing_optimization")


def test_validate_flow_config_preserves_explicit_true_and_folds_skips():
    assert validate_flow_config({"preset": "rtl2gds", "no_clock": True}) == {
        "preset": "rtl2gds",
        "no_clock": True,
        "skip_steps": list(_NO_CLOCK_SKIPS),
    }


def test_validate_flow_config_preserves_explicit_false_as_policy():
    assert validate_flow_config({"no_clock": False}) == {"no_clock": False}
    assert validate_flow_config({"preset": "rtl2gds", "no_clock": False, "skip_steps": []}) == {
        "preset": "rtl2gds",
        "no_clock": False,
        "skip_steps": [],
    }


@pytest.mark.parametrize(
    ("flow_policy", "materials", "clock", "expected_flow", "expected_skips"),
    [
        (
            {},
            {"clock_port": " \t"},
            " \t",
            {
                "preset": "rtl2gds",
                "no_clock": True,
                "skip_steps": list(_NO_CLOCK_SKIPS),
            },
            _NO_CLOCK_SKIPS,
        ),
        (
            {"no_clock": False, "skip_steps": []},
            {"clock_port": ""},
            "",
            {"preset": "rtl2gds", "no_clock": False, "skip_steps": []},
            (),
        ),
        (
            {},
            {"clock_port": "clk"},
            "clk",
            {"preset": "rtl2gds"},
            ("diff_opt",),
        ),
    ],
)
def test_effective_policy_persists_and_reloads_coherently(
    tmp_path, flow_policy, materials, clock, expected_flow, expected_skips
):
    flow_config = {"preset": "rtl2gds", **flow_policy}
    original = deepcopy(flow_config)
    section = flow_section_from_flow_config(flow_config, materials=materials)
    assert section == expected_flow
    assert flow_config == original

    payload = {"design": "gcd", "top_module": "gcd", "clock": clock}
    assert save_workspace_config(tmp_path, payload, section)
    loaded = load_workspace_config(tmp_path)

    assert loaded == {**payload, "_flow": expected_flow}
    assert (
        resolve_skip_steps(loaded["_flow"], materials={"clock_port": loaded["clock"]})
        == expected_skips
    )


@pytest.mark.parametrize("flag", [None, 0, 1, "true", "false", [], {}])
def test_flow_persistence_rejects_invalid_no_clock_flags(flag):
    with pytest.raises(WorkspaceFlowTargetError, match="no_clock must be a boolean"):
        validate_flow_config({"no_clock": flag})
    with pytest.raises(WorkspaceFlowTargetError, match="no_clock must be a boolean"):
        flow_section_from_flow_config({"preset": "rtl2gds", "no_clock": flag})


def test_flow_persistence_rejects_invalid_clock_material():
    with pytest.raises(
        WorkspaceFlowTargetError, match="clock_port clock material must be a string"
    ):
        flow_section_from_flow_config({"preset": "rtl2gds"}, materials={"clock_port": None})


def test_inferred_and_explicit_no_clock_build_the_same_ledger():
    inferred = build_dynamic_flow_data({"preset": "rtl2gds"}, materials={"clock_port": ""})
    explicit = build_dynamic_flow_data({"preset": "rtl2gds", "no_clock": True})

    assert inferred == explicit
    names = {step["name"] for step in inferred.get("steps", [])}
    assert names.isdisjoint(_NO_CLOCK_SKIPS)
    assert {"placement", "legalization", "routing"} <= names


def test_retained_clock_and_explicit_false_preserve_the_existing_ledger():
    baseline = build_dynamic_flow_data({"preset": "rtl2gds"})

    assert (
        build_dynamic_flow_data({"preset": "rtl2gds"}, materials={"clock_port": "clk"}) == baseline
    )
    assert (
        build_dynamic_flow_data(
            {"preset": "rtl2gds", "no_clock": False}, materials={"clock_port": ""}
        )
        == baseline
    )


@pytest.mark.parametrize("boundary", _NO_CLOCK_SKIPS)
def test_no_clock_steps_cannot_bound_a_persisted_range(boundary):
    with pytest.raises(WorkspaceFlowTargetError, match="cannot bound the flow range"):
        validate_flow_config({"start": boundary, "end": "routing", "no_clock": True})
    with pytest.raises(WorkspaceFlowTargetError, match="cannot bound the flow range"):
        validate_flow_config({"start": "synthesis", "end": boundary, "no_clock": True})


@pytest.mark.parametrize(
    ("no_clock", "expected_steps", "expected_skips"),
    [
        (
            True,
            ["placement", "legalization", "routing"],
            list(_NO_CLOCK_SKIPS),
        ),
        (
            False,
            [
                "placement",
                "diff_opt",
                "diff_sizing",
                "cts",
                "legalization",
                "timing_optimization",
                "routing",
            ],
            [],
        ),
    ],
)
def test_created_workspace_reloads_the_effective_no_clock_policy(
    tmp_path,
    minimal_ics55_pdk_factory,
    default_ics55_parameters,
    no_clock,
    expected_steps,
    expected_skips,
):
    from chipcompiler.data import create_workspace, load_workspace

    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    netlist_path = tmp_path / "gcd.v"
    netlist_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    parameters = deepcopy(default_ics55_parameters)
    parameters["clock"] = ""
    workspace_dir = tmp_path / "workspace"

    workspace = create_workspace(
        directory=workspace_dir,
        origin_def="",
        origin_verilog=netlist_path,
        pdk="ics55",
        parameters=parameters,
        pdk_root=pdk_root,
        flow_config={
            "start_step": "placement",
            "end_step": "routing",
            "no_clock": no_clock,
            "skip_steps": [],
        },
    )

    assert workspace is not None
    loaded = load_workspace(str(workspace_dir))
    assert [step["name"] for step in loaded.flow.steps()] == expected_steps
    assert loaded.parameters.data["_flow"] == {
        "start": "placement",
        "end": "routing",
        "no_clock": no_clock,
        "skip_steps": expected_skips,
    }
    assert resolve_skip_steps(
        loaded.parameters.data["_flow"],
        materials={"clock_port": loaded.parameters.data["clock"]},
    ) == tuple(expected_skips)


def test_create_workspace_rejects_invalid_no_clock_before_mutation(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
):
    from chipcompiler.data import create_workspace

    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    netlist_path = tmp_path / "gcd.v"
    netlist_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    workspace_dir = tmp_path / "workspace"

    with pytest.raises(ValueError, match="no_clock must be a boolean"):
        create_workspace(
            directory=workspace_dir,
            origin_def="",
            origin_verilog=netlist_path,
            pdk="ics55",
            parameters=deepcopy(default_ics55_parameters),
            pdk_root=pdk_root,
            flow_config={"preset": "rtl2gds", "no_clock": "false"},
        )

    assert not workspace_dir.exists()
