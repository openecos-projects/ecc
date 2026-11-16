"""PR #412 review reproductions: no-clock normalization and lifecycle fixes.

These are review-level regression tests for the two runtime findings:
  * empty clock materials must infer no-clock during workspace creation
  * policy-only and derived-range transforms must preserve ``no_clock``

They also pin the review's single-normalization requirement and the
explicit-false override / CTS gate branches.
"""

import inspect
from types import SimpleNamespace

import pytest

from chipcompiler import rtl2gds as rtl2gds_api
from chipcompiler.cli.inspection.config_view import build_project_config_items
from chipcompiler.cli.project.config import ProjectConfig
from chipcompiler.cli.project.effective_config import (
    _attach_no_clock,
    skip_steps_shadow_warning,
)
from chipcompiler.data import create_workspace
from chipcompiler.data.types import SkippableStepEnum
from chipcompiler.data.workspace_config import (
    WorkspaceFlowTargetError,
    coerce_bool,
    flow_no_clock,
    validate_flow_config,
)
from chipcompiler.engine import EngineFlow
from chipcompiler.engine.workspace_derive_range import bound_derived_flow
from chipcompiler.rtl2gds import builder as rtl2gds_builder
from chipcompiler.rtl2gds import resolve_no_clock, resolve_skip_steps


def _make_workspace(tmp_path, minimal_ics55_pdk_factory, flow_config, *, clock="clk"):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "pdk")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    workspace = create_workspace(
        directory=tmp_path / "workspace",
        origin_def="",
        origin_verilog=rtl_path,
        pdk="ics55",
        parameters={
            "pdk": "ics55",
            "design": "gcd",
            "top_module": "gcd",
            "clock": clock,
            "frequency_max": 100,
        },
        pdk_root=pdk_root,
        flow_config=flow_config,
    )
    assert workspace is not None
    return workspace


def _ledger_names(workspace):
    return [step["name"] for step in workspace.flow.data.get("steps", [])]


def test_workspace_infers_no_clock(tmp_path, minimal_ics55_pdk_factory):
    workspace = _make_workspace(
        tmp_path,
        minimal_ics55_pdk_factory,
        {"preset": "rtl2gds"},
        clock="",
    )

    names = _ledger_names(workspace)
    assert "CTS" not in names
    assert SkippableStepEnum.PREPLACE.value not in names
    assert SkippableStepEnum.DIFF_OPT.value not in names
    assert SkippableStepEnum.DIFF_SIZING.value not in names
    assert SkippableStepEnum.TIMING_OPT.value not in names

    persisted = workspace.parameters.data.get("_flow", {})
    assert persisted.get("no_clock") is True
    assert "CTS" in persisted.get("skip_steps", [])


def test_policy_only_cts_skip_creates_workspace(tmp_path, minimal_ics55_pdk_factory):
    workspace = _make_workspace(
        tmp_path,
        minimal_ics55_pdk_factory,
        {"no_clock": True, "skip_steps": ["CTS"]},
    )

    flow = workspace.parameters.data.get("_flow", {})
    assert flow.get("no_clock") is True
    assert "CTS" in flow.get("skip_steps", [])

    # Policy-only configs have no ledger by definition; resolve the persisted
    # policy back through the real builder to prove CTS is actually omitted.
    resolved = resolve_skip_steps(flow)
    built_names = [
        step.value if hasattr(step, "value") else str(step)
        for step, _tool, _state in rtl2gds_api.build_rtl2gds_flow(skip=resolved)
    ]
    assert "CTS" not in built_names
    assert SkippableStepEnum.PREPLACE.value not in built_names


def test_derived_range_retains_no_clock(tmp_path, minimal_ics55_pdk_factory):
    workspace = _make_workspace(
        tmp_path,
        minimal_ics55_pdk_factory,
        {"preset": "rtl2gds", "no_clock": True},
    )
    flow = EngineFlow(workspace=workspace)

    bound_derived_flow(workspace, flow, "Synthesis", "route")

    persisted = workspace.parameters.data.get("_flow", {})
    assert persisted.get("no_clock") is True
    assert "CTS" in persisted.get("skip_steps", [])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        (2.5, True),
        (0.0, False),
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("on", True),
        (" false ", False),
        ("off", False),
        ("", False),
        (None, False),
    ],
)
def test_coerce_bool_truth_table(value, expected):
    assert coerce_bool(value) is expected


def test_flow_no_clock_is_data_owned_and_builder_has_no_private_coercer():
    assert flow_no_clock({"no_clock": "yes"}) is True
    assert flow_no_clock({"no_clock": "off"}) is False
    assert rtl2gds_builder.flow_no_clock({"no_clock": 1}) is True
    assert not hasattr(rtl2gds_builder, "_coerce_no_clock_flag")

    source = inspect.getsource(rtl2gds_builder.flow_no_clock)
    assert "chipcompiler.data.workspace_config" in source


def test_project_config_parse_uses_data_owned_flow_no_clock(tmp_path, monkeypatch):
    import chipcompiler.cli.project.config as config_module
    import chipcompiler.data.workspace_config as workspace_config

    monkeypatch.setattr(workspace_config, "flow_no_clock", lambda flow: "from-data-layer")
    cfg = config_module._parse_config({"flow": {"no_clock": True}}, str(tmp_path / "ecc.toml"))

    assert cfg.flow_no_clock == "from-data-layer"


def test_explicit_false_overrides_empty_clock_inference():
    decision = resolve_no_clock({"no_clock": False}, materials={"clock_port": ""})

    assert decision.enabled is False
    assert decision.source == "off"
    assert "CTS" not in resolve_skip_steps({"no_clock": False}, materials={"clock_port": ""})
    assert resolve_skip_steps({"no_clock": False}, materials={"clock_port": ""}) == (
        "lec",
        "diff_opt",
    )


def test_cts_gate_is_strict_without_no_clock():
    with pytest.raises(WorkspaceFlowTargetError, match="CTS"):
        validate_flow_config({"skip_steps": ["CTS"]})

    with pytest.raises(ValueError, match="CTS"):
        resolve_skip_steps({"skip_steps": ["CTS"]}, materials={"clock_port": "clk"})


def test_attach_no_clock_carries_inferred_effective_flag():
    flow_config = _attach_no_clock(
        {"skip_steps": ["lec"]},
        no_clock_decision=rtl2gds_builder.NoClockDecision(enabled=True, source="inferred"),
    )

    assert flow_config == {"skip_steps": ["lec"], "no_clock": True}
    assert (
        _attach_no_clock(
            None,
            no_clock_decision=rtl2gds_builder.NoClockDecision(enabled=False, source="off"),
        )
        is None
    )


def test_skip_steps_shadow_warning_uses_no_clock_context():
    cfg = SimpleNamespace(
        _explicit_keys=frozenset({"flow.skip_steps", "flow.no_clock"}),
        flow_skip_steps=["CTS"],
        flow_no_clock=True,
        design_clock_port="clk",
        design_frequency_mhz=100.0,
        flow_lec_engine=None,
    )
    entry = SimpleNamespace(skip_steps=["lec"])

    warning = skip_steps_shadow_warning(entry, cfg)

    assert warning is not None
    assert warning["warning"] == "skip_steps_shadowed"


def test_config_view_reports_inferred_no_clock(tmp_path):
    cfg = ProjectConfig(
        design_name="gcd",
        design_top="gcd",
        design_clock_port="",
        pdk_name="ics55",
        flow_preset="rtl2gds",
        project_dir=str(tmp_path),
    )
    cfg._no_clock_source = "inferred"

    items, status = build_project_config_items(
        str(tmp_path),
        str(tmp_path / "run"),
        resolved=(cfg, None),
    )

    assert status == 0
    values = {
        item["key"]: item["value"]
        for item in items
        if item["key"] in {"flow.no_clock", "flow.no_clock_source"}
    }
    assert values == {"flow.no_clock": True, "flow.no_clock_source": "inferred"}
