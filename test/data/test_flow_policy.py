"""The flow policy table is exhaustive and owns the derived step views."""

from chipcompiler.data.types import (
    ADVISORY_FLOW_STEPS,
    FLOW_STEP_CATEGORIES,
    FLOW_STEP_POLICIES,
    SkippableStepEnum,
    StepEnum,
)


def _flow_step_values() -> set[str]:
    # `FLOORPLAN` is a shared configuration key, not a flow step.
    return {member.value for member in StepEnum if member is not StepEnum.FLOORPLAN} | {
        member.value for member in SkippableStepEnum
    }


def test_every_flow_step_has_a_policy():
    assert set(FLOW_STEP_POLICIES) == _flow_step_values()


def test_category_and_advisory_views_derive_from_the_policy_table():
    categories = {name: policy.category for name, policy in FLOW_STEP_POLICIES.items()}
    advisory = {name for name, policy in FLOW_STEP_POLICIES.items() if policy.advisory}
    assert categories == FLOW_STEP_CATEGORIES
    assert advisory == ADVISORY_FLOW_STEPS
