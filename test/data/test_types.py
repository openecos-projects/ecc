import pytest

from chipcompiler.data.types import (
    DEFAULT_LEC_ENGINE,
    LEC_STEP_TOOLS,
    LECEngineEnum,
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


def test_lec_engine_enum_members_and_derived_constants():
    assert {member.value for member in LECEngineEnum} == {
        "yosys_lec",
        "kepler_formal",
        "lec_dual",
    }
    assert frozenset(member.value for member in LECEngineEnum) == LEC_STEP_TOOLS
    assert DEFAULT_LEC_ENGINE is LECEngineEnum.KEPLER_FORMAL


@pytest.mark.parametrize(
    "raw,expected",
    [
        *[(member.value, member) for member in LECEngineEnum],
        *[(member, member) for member in LECEngineEnum],
        ("dual", LECEngineEnum.DUAL),
    ],
)
def test_lec_engine_from_value_accepts_member_values_and_the_dual_alias(raw, expected):
    assert LECEngineEnum.from_value(raw) is expected


def test_lec_engine_from_value_normalizes_the_dual_alias_away():
    # Persisted/ledger strings are always the member value, never the alias.
    assert LECEngineEnum.from_value("dual").value == "lec_dual"
    assert "dual" not in {member.value for member in LECEngineEnum}


def test_lec_engine_from_value_rejects_unknown_values_with_the_legal_set():
    with pytest.raises(ValueError, match="unknown LEC engine: 'nonsense'.*yosys_lec"):
        LECEngineEnum.from_value("nonsense")


def test_spawn_engines_fans_out_only_for_dual():
    assert LECEngineEnum.DUAL.spawn_engines == (
        LECEngineEnum.YOSYS_LEC,
        LECEngineEnum.KEPLER_FORMAL,
    )
    assert LECEngineEnum.YOSYS_LEC.spawn_engines == (LECEngineEnum.YOSYS_LEC,)
    assert LECEngineEnum.KEPLER_FORMAL.spawn_engines == (LECEngineEnum.KEPLER_FORMAL,)
