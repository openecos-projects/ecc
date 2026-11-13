"""The declared design data keeps the canonical chain and its variants runnable."""

from itertools import chain, combinations

import pytest

from chipcompiler.data.flow_check import FlowViolation, Severity, check_flow
from chipcompiler.data.types import (
    AnalysisData,
    DesignState,
    FlowStepCategory,
    FlowStepPolicy,
    SkippableStepEnum,
)
from chipcompiler.rtl2gds import build_rtl2gds_flow

_FROM_RTL = frozenset({DesignState.RTL})


def _chain(*, without: tuple[str, ...] = ()) -> list[str]:
    names = [step.value for step, _tool, _state in build_rtl2gds_flow()]
    return [name for name in names if name not in without]


def _warning(step: str, *missing) -> FlowViolation:
    return FlowViolation(step, Severity.WARNING, frozenset(missing))


def _error(step: str, *missing) -> FlowViolation:
    return FlowViolation(step, Severity.ERROR, frozenset(missing))


_SKIPPABLE = [member.value for member in SkippableStepEnum]


@pytest.mark.parametrize(
    "skipped",
    list(chain.from_iterable(combinations(_SKIPPABLE, n) for n in range(len(_SKIPPABLE) + 1))),
)
def test_skipping_any_skippable_steps_keeps_the_chain_runnable(skipped):
    assert check_flow(_chain(without=skipped), available=_FROM_RTL) == ()


def test_flow_without_clock_tree_runs_on_ideal_clocks():
    violations = check_flow(_chain(without=("CTS",)), available=_FROM_RTL)

    assert violations == (
        _warning("route", DesignState.CLOCK_TREE),
        _warning("sta", DesignState.CLOCK_TREE),
        _warning("powerAnalysis", DesignState.CLOCK_TREE),
        _warning("Harden", DesignState.CLOCK_TREE),
    )


@pytest.mark.parametrize(
    ("without", "expected"),
    [
        # Timing optimization legalizes its own sizing, so it covers CTS too.
        (("legalization",), ()),
        (("legalization", "Timing optimization"), (_error("route", DesignState.LEGAL),)),
        # Placement is legal; nothing between it and routing needs legalizing.
        (
            ("CTS", "legalization", "Timing optimization"),
            (_warning("route", DesignState.CLOCK_TREE),),
        ),
    ],
)
def test_routing_needs_a_legal_placement(without, expected):
    violations = check_flow(_chain(without=without), available=_FROM_RTL)

    assert [violation for violation in violations if violation.step == "route"] == list(expected)


def test_analysis_before_its_source_is_an_error():
    names = _chain()
    names.remove("sta")
    names.insert(names.index("RCX"), "sta")

    assert check_flow(names, available=_FROM_RTL) == (_error("sta", AnalysisData.PARASITICS),)


def test_declared_inputs_stand_in_for_steps_outside_the_flow():
    filled = frozenset({DesignState.FILLED, DesignState.CLOCK_TREE})

    assert check_flow(["sta"], available=filled) == (_error("sta", AnalysisData.PARASITICS),)
    assert check_flow(["sta"], available=filled | {AnalysisData.PARASITICS}) == ()


def test_unknown_step_is_rejected():
    with pytest.raises(ValueError, match="no flow policy registered"):
        check_flow(["Spin"], available=_FROM_RTL)


def test_legality_is_declared_only_through_the_legality_field():
    with pytest.raises(ValueError, match="legality"):
        FlowStepPolicy(FlowStepCategory.PNR, provides=frozenset({DesignState.LEGAL}))


def test_design_data_is_either_required_or_optional():
    with pytest.raises(ValueError, match="both required and optional"):
        FlowStepPolicy(
            FlowStepCategory.PNR,
            requires=frozenset({DesignState.PLACED}),
            uses=frozenset({DesignState.PLACED}),
        )
