import pytest

from chipcompiler.data.types import (
    SkippableStepEnum,
    StepBaseEnum,
    StepEnum,
    step_from_value,
)


def test_step_base_enum_defines_no_members_and_defaults_to_not_skippable():
    assert len(list(StepBaseEnum)) == 0
    assert StepEnum.SYNTHESIS.is_skippable() is False


def test_skippable_step_enum_members_are_marked_skippable():
    assert {member.name for member in SkippableStepEnum} == {
        "LEC",
        "POST_ROUTE_LEC",
        "TIMING_OPT",
    }
    assert all(member.is_skippable() is True for member in SkippableStepEnum)
    assert {member.value for member in SkippableStepEnum} == {
        "lec",
        "postRouteLec",
        "Timing optimization",
    }


def test_core_enum_no_longer_carries_the_skippable_members():
    for name in ("LEC", "POST_ROUTE_LEC", "TIMING_OPT"):
        assert not hasattr(StepEnum, name)
        with pytest.raises(ValueError):
            StepEnum(getattr(SkippableStepEnum, name).value)


def test_both_enums_share_the_memberless_base():
    assert issubclass(StepEnum, StepBaseEnum)
    assert issubclass(SkippableStepEnum, StepBaseEnum)


@pytest.mark.parametrize(
    "value,expected",
    [(member.value, member) for member in (*StepEnum, *SkippableStepEnum)],
)
def test_step_from_value_resolves_both_enums(value, expected):
    assert step_from_value(value) is expected


def test_step_from_value_rejects_unknown_values():
    with pytest.raises(ValueError, match="unknown flow step: 'bogus'"):
        step_from_value("bogus")
