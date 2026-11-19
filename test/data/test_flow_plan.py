"""A step selection is a preset chain minus skipped steps, checked by capability."""

import pytest

from chipcompiler.data import DEFAULT_SKIP_STEPS
from chipcompiler.data.flow.check import Severity
from chipcompiler.data.flow.needs import StepNeeds, plan_needs
from chipcompiler.data.flow.plan import (
    FlowPlan,
    PlannedStep,
    PlanViolation,
    inserted_chain,
    plan_flow,
    preset_chain,
)
from chipcompiler.data.types import AnalysisData, DesignState

_RTL2GDS = preset_chain("rtl2gds")


def test_plan_marks_skipped_and_optional_steps():
    plan = plan_flow(_RTL2GDS, skip_steps=["diff_opt"], start="placement", end="diff_sizing")

    assert plan == FlowPlan(
        steps=(
            PlannedStep("placement", "dreamplace", enabled=True, optional=False),
            PlannedStep("diff_opt", "dreamplace", enabled=False, optional=True),
            PlannedStep("diff_sizing", "dreamplace", enabled=True, optional=False),
        ),
        available=frozenset(
            {
                DesignState.RTL,
                DesignState.NETLIST,
                AnalysisData.GOLDEN_NETLIST,
                DesignState.FLOORPLAN,
                DesignState.MACROS_PLACED,
                DesignState.PDN,
            }
        ),
        violations=(),
    )


def test_default_skip_policy_plans_a_clean_chain():
    plan = plan_flow(_RTL2GDS, skip_steps=DEFAULT_SKIP_STEPS)

    assert (plan.skip_steps, plan.violations) == (DEFAULT_SKIP_STEPS, ())
    assert plan.enabled_steps == tuple(
        name for name, _tool in _RTL2GDS if name not in DEFAULT_SKIP_STEPS
    )


def test_skipping_cts_degrades_timing_steps_and_names_cts_as_the_fix():
    plan = plan_flow(_RTL2GDS, skip_steps=["cts"])

    missing = frozenset({DesignState.CLOCK_TREE})
    assert plan.violations == tuple(
        PlanViolation(step, Severity.WARNING, missing, ("cts",))
        for step in ("routing", "sta", "power_analysis", "harden")
    )
    assert plan.errors == ()
    assert plan.warnings[0].message() == (
        "routing runs with degraded results without clock_tree; enable cts"
    )


def test_unlegalized_clock_tree_blocks_routing_and_names_every_legalizing_fix():
    plan = plan_flow(_RTL2GDS, skip_steps=["diff_opt", "legalization", "timing_optimization"])

    # diff_opt legalizes too, but CTS runs after it, so enabling it is no fix.
    error = PlanViolation(
        "routing",
        Severity.ERROR,
        frozenset({DesignState.LEGAL}),
        ("timing_optimization", "legalization"),
    )
    assert plan.errors == (error,)
    assert error.message() == "routing requires legal; enable timing_optimization or legalization"


def test_leading_steps_are_supplied_by_the_entry_inputs():
    plan = plan_flow(_RTL2GDS, skip_steps=["synthesis", "diff_opt"])

    assert plan.enabled_steps[0] == "pre_floorplan"
    assert plan.available == frozenset(
        {DesignState.RTL, DesignState.NETLIST, AnalysisData.GOLDEN_NETLIST}
    )
    assert plan.violations == ()


def test_range_plans_only_its_steps_and_starts_from_the_chain_prefix():
    plan = plan_flow(_RTL2GDS, skip_steps=DEFAULT_SKIP_STEPS, start="rcx", end="sta")

    assert plan == FlowPlan(
        steps=(
            PlannedStep("rcx", "ecc", enabled=True, optional=False),
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
    plan = plan_flow(_RTL2GDS, skip_steps=["rcx"])

    missing = frozenset({AnalysisData.PARASITICS})
    assert plan.errors == tuple(
        PlanViolation(step, Severity.ERROR, missing, ("rcx",))
        for step in ("sta", "power_analysis", "harden")
    )


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"start": "Spin"}, "unknown flow step: 'Spin'"),
        ({"start": "routing", "end": "cts"}, "reversed"),
        ({"skip_steps": ["harden"]}, "'harden' ends the flow"),
        ({"skip_steps": ["routing"], "end": "routing"}, "'routing' ends the flow"),
        ({"skip_steps": ["cts"], "start": "cts"}, "'cts' starts the flow range"),
    ],
)
def test_invalid_selections_are_rejected(kwargs, match):
    with pytest.raises(ValueError, match=match):
        plan_flow(_RTL2GDS, **kwargs)


def test_unknown_preset_is_rejected():
    with pytest.raises(ValueError, match="unknown flow preset: 'harden'"):
        preset_chain("harden")


def test_an_inserted_step_follows_its_step_and_is_enabled_with_it():
    plan = plan_flow(
        _RTL2GDS,
        skip_steps=["cts"],
        inserted=inserted_chain(["lec@placement", "lec@cts"]),
        start="placement",
        end="legalization",
    )

    assert plan.steps == (
        PlannedStep("placement", "dreamplace", enabled=True, optional=False),
        PlannedStep("lec@placement", "kepler_formal", enabled=True, optional=True, inserted=True),
        PlannedStep("diff_opt", "dreamplace", enabled=True, optional=True),
        PlannedStep("diff_sizing", "dreamplace", enabled=True, optional=False),
        PlannedStep("cts", "ecc", enabled=False, optional=False),
        PlannedStep("lec@cts", "kepler_formal", enabled=False, optional=True, inserted=True),
        PlannedStep("legalization", "dreamplace", enabled=True, optional=False),
    )
    # An inserted step is declared by insert_steps, never skipped.
    assert (plan.skip_steps, plan.insert_steps) == (("cts",), ("lec@placement", "lec@cts"))


def test_a_preset_built_check_is_planned_as_an_insertion_of_its_step():
    plan = plan_flow(preset_chain("synthesis_lec"))

    assert plan.steps == (
        PlannedStep("synthesis", "yosys", enabled=True, optional=False),
        PlannedStep("lec@synthesis", "kepler_formal", enabled=True, optional=True, inserted=True),
    )
    # Synthesis is the flow target; the check cannot run without it.
    with pytest.raises(ValueError, match="'synthesis' ends the flow"):
        plan_flow(preset_chain("synthesis_lec"), skip_steps=["synthesis"])


def test_an_inserted_check_follows_the_step_it_checks_first():
    plan = plan_flow(_RTL2GDS, skip_steps=DEFAULT_SKIP_STEPS, inserted=inserted_chain(["lec@cts"]))
    position = plan.enabled_steps.index("lec@cts")
    steps = [step for step in plan.steps if step.enabled]

    assert plan_needs(steps)[position] == StepNeeds(
        producers=(("golden_netlist", "synthesis"), ("netlist", "synthesis")),
        after=("cts", "synthesis"),
    )
