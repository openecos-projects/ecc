"""The flow policy table is exhaustive and owns the derived step views."""

import pytest

from chipcompiler.data.types import (
    ADVISORY_FLOW_STEPS,
    FLOW_STEP_CATEGORIES,
    FLOW_STEP_POLICIES,
    SkippableStepEnum,
    StepEnum,
    flow_step_policy,
)
from chipcompiler.data.workspace.flow_data import build_dynamic_flow_data
from chipcompiler.data.workspace.flow_policy import FlowInputResolver


def _flow_step_values() -> set[str]:
    return {member.value for member in StepEnum} | {member.value for member in SkippableStepEnum}


def test_every_flow_step_has_a_policy():
    assert set(FLOW_STEP_POLICIES) == _flow_step_values()


def test_only_a_canonical_inserted_step_has_the_lec_policy():
    lec = FLOW_STEP_POLICIES[StepEnum.LEC.value]
    assert [flow_step_policy(name) for name in ("lec@Synthesis", "lec@Timing_optimization")] == [
        lec,
        lec,
    ]
    # lec@ must be followed by a step an LEC can be inserted after.
    for name in ("lec@bogus", "lec@filler", "lec@", "lec@Timing optimization"):
        with pytest.raises(ValueError, match="no flow policy registered"):
            flow_step_policy(name)


def test_category_and_advisory_views_derive_from_the_policy_table():
    categories = {name: policy.category for name, policy in FLOW_STEP_POLICIES.items()}
    advisory = {name for name, policy in FLOW_STEP_POLICIES.items() if policy.advisory}
    assert categories == FLOW_STEP_CATEGORIES
    assert advisory == ADVISORY_FLOW_STEPS


def _waves(records):
    from chipcompiler.data.workspace.flow_policy import analysis_wave_end

    waves, index = [], 0
    while index < len(records):
        end = analysis_wave_end(records, index)
        waves.append([record["name"] for record in records[index:end]])
        index = end
    return waves


def test_independent_signoff_analyses_form_parallel_waves():
    from chipcompiler.data.workspace.flow_data import build_dynamic_flow_data

    ledger = build_dynamic_flow_data(
        {"start_step": "route", "end_step": "Harden", "skip_steps": []}
    )

    assert _waves(ledger.get("steps", [])) == [
        ["route"],
        ["filler"],
        ["lvs", "drc", "antennaCheck", "postRouteLec", "RCX"],
        ["sta", "powerAnalysis"],
        ["emir"],
        ["Harden"],
    ]


def test_an_explicit_input_inside_a_wave_starts_a_new_wave():
    from chipcompiler.data.workspace.flow_data import build_dynamic_flow_data

    ledger = build_dynamic_flow_data({"start_step": "filler", "end_step": "RCX", "skip_steps": []})
    steps = ledger.get("steps", [])
    next(step for step in steps if step["name"] == "drc")["input_step"] = "lvs"

    assert _waves(steps) == [
        ["filler"],
        ["lvs"],
        ["drc", "antennaCheck", "postRouteLec", "RCX"],
    ]


def test_ledgers_without_categories_run_every_step_alone():
    records = [{"name": "lvs", "tool": "ecc"}, {"name": "drc", "tool": "ecc"}]

    assert _waves(records) == [["lvs"], ["drc"]]


def test_skipped_steps_hand_their_input_to_the_next_enabled_step():
    ledger = build_dynamic_flow_data(
        {
            "start_step": "place",
            "end_step": "route",
            "skip_steps": ["diff_opt", "diff_sizing", "CTS"],
        }
    )
    records = ledger.get("steps", [])
    resolver = FlowInputResolver(records)

    assert {
        step["name"]: resolver.input_step_name(index) for index, step in enumerate(records)
    } == {
        "place": None,
        "legalization": "place",
        "Timing optimization": "legalization",
        "route": "Timing optimization",
    }
