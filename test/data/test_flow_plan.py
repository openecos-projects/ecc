"""A step selection is a preset chain minus skipped steps, checked by capability."""

import pytest

from chipcompiler.data import DEFAULT_SKIP_STEPS
from chipcompiler.data.flow_check import Severity
from chipcompiler.data.flow_plan import (
    FlowPlan,
    PlannedStep,
    PlanViolation,
    plan_flow,
    preset_chain,
)
from chipcompiler.data.types import AnalysisData, DesignState

_RTL2GDS = preset_chain("rtl2gds")


def test_plan_marks_skipped_and_optional_steps():
    chain = preset_chain("rtl2gds", lec_engine="yosys_lec")
    plan = plan_flow(chain, skip_steps=["lec"], start="Synthesis", end="preFloorplan")

    assert plan == FlowPlan(
        steps=(
            PlannedStep("Synthesis", "yosys", enabled=True, optional=False),
            PlannedStep("lec", "yosys_lec", enabled=False, optional=True),
            PlannedStep("preFloorplan", "ecc", enabled=True, optional=False),
        ),
        available=frozenset({DesignState.RTL}),
        violations=(),
    )


def test_default_skip_policy_plans_a_clean_chain():
    plan = plan_flow(_RTL2GDS, skip_steps=DEFAULT_SKIP_STEPS)

    assert (plan.skip_steps, plan.violations) == (DEFAULT_SKIP_STEPS, ())
    assert plan.enabled_steps == tuple(
        name for name, _tool in _RTL2GDS if name not in DEFAULT_SKIP_STEPS
    )


def test_skipping_cts_degrades_timing_steps_and_names_cts_as_the_fix():
    plan = plan_flow(_RTL2GDS, skip_steps=["CTS"])

    missing = frozenset({DesignState.CLOCK_TREE})
    assert plan.violations == tuple(
        PlanViolation(step, Severity.WARNING, missing, ("CTS",))
        for step in ("route", "sta", "powerAnalysis", "Harden")
    )
    assert plan.errors == ()
    assert plan.warnings[0].message() == (
        "route runs with degraded results without clock_tree; enable CTS"
    )


def test_unlegalized_clock_tree_blocks_routing_and_names_every_legalizing_fix():
    plan = plan_flow(_RTL2GDS, skip_steps=["diff_opt", "legalization", "Timing optimization"])

    # diff_opt legalizes too, but CTS runs after it, so enabling it is no fix.
    error = PlanViolation(
        "route",
        Severity.ERROR,
        frozenset({DesignState.LEGAL}),
        ("Timing optimization", "legalization"),
    )
    assert plan.errors == (error,)
    assert error.message() == "route requires legal; enable Timing optimization or legalization"


def test_leading_steps_are_supplied_by_the_entry_inputs():
    plan = plan_flow(_RTL2GDS, skip_steps=["Synthesis", "lec", "diff_opt"])

    assert plan.enabled_steps[0] == "preFloorplan"
    assert plan.available == frozenset(
        {DesignState.RTL, DesignState.NETLIST, AnalysisData.GOLDEN_NETLIST}
    )
    assert plan.violations == ()


def test_range_plans_only_its_steps_and_starts_from_the_chain_prefix():
    plan = plan_flow(_RTL2GDS, skip_steps=DEFAULT_SKIP_STEPS, start="RCX", end="sta")

    assert plan == FlowPlan(
        steps=(
            PlannedStep("RCX", "ecc", enabled=True, optional=False),
            PlannedStep("sta", "ecc", enabled=True, optional=False),
        ),
        available=frozenset(
            {
                DesignState.RTL,
                DesignState.NETLIST,
                AnalysisData.GOLDEN_NETLIST,
                DesignState.FLOORPLAN,
                DesignState.MACROS_PLACED,
                DesignState.PDN,
                DesignState.PLACED,
                DesignState.CLOCK_TREE,
                DesignState.LEGAL,
                DesignState.ROUTED,
                DesignState.FILLED,
            }
        ),
        violations=(),
    )


def test_skipping_an_analysis_source_blocks_its_consumers():
    plan = plan_flow(_RTL2GDS, skip_steps=["RCX"])

    missing = frozenset({AnalysisData.PARASITICS})
    assert plan.errors == tuple(
        PlanViolation(step, Severity.ERROR, missing, ("RCX",))
        for step in ("sta", "powerAnalysis", "Harden")
    )


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"start": "Spin"}, "unknown flow step: 'Spin'"),
        ({"start": "route", "end": "CTS"}, "reversed"),
        ({"skip_steps": ["Harden"]}, "'Harden' ends the flow"),
        ({"skip_steps": ["route"], "end": "route"}, "'route' ends the flow"),
        ({"skip_steps": ["CTS"], "start": "CTS"}, "'CTS' starts the flow range"),
    ],
)
def test_invalid_selections_are_rejected(kwargs, match):
    with pytest.raises(ValueError, match=match):
        plan_flow(_RTL2GDS, **kwargs)


def test_unknown_preset_is_rejected():
    with pytest.raises(ValueError, match="unknown flow preset: 'harden'"):
        preset_chain("harden")
