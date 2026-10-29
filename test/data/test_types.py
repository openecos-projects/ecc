import pytest

from chipcompiler.data.types import (
    DEFAULT_LEC_ENGINE,
    LEC_STEP_TOOLS,
    FlowStepCategory,
    LECEngineEnum,
    SkippableStepEnum,
    StateEnum,
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
        "DIFF_OPT",
        "POST_ROUTE_LEC",
        "TIMING_OPT",
    }
    assert all(member.is_skippable() is True for member in SkippableStepEnum)
    assert {member.value for member in SkippableStepEnum} == {
        "lec",
        "diff_opt",
        "postRouteLec",
        "Timing optimization",
    }


def test_core_enum_no_longer_carries_the_skippable_members():
    for name in ("LEC", "DIFF_OPT", "POST_ROUTE_LEC", "TIMING_OPT"):
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


def test_enum_members_render_and_compare_as_their_persisted_values():
    # The persistence contract is the member value. Rendering is asserted on
    # the production hierarchy because a wrong base order (`StrEnum` before
    # `StepBaseEnum`) silently renders `ClassName.MEMBER` instead.
    for member in (*StepEnum, *SkippableStepEnum, *LECEngineEnum):
        assert str(member) == member.value
        assert f"{member}" == member.value
        assert member == member.value
    assert str(FlowStepCategory.CHECKER) == FlowStepCategory.CHECKER.value
    assert str(StateEnum.Success) == StateEnum.Success.value


def test_step_hierarchy_survives_the_string_enum_base():
    assert isinstance(StepEnum.STA, StepBaseEnum)
    assert isinstance(SkippableStepEnum.LEC, StepBaseEnum)
    assert isinstance(StepEnum.STA, str)
    assert StepEnum.SYNTHESIS.is_skippable() is False
    assert SkippableStepEnum.LEC.is_skippable() is True


def test_yaml_safe_dump_rejects_enum_members():
    import yaml

    # YAML sinks in the codebase receive plain `str`; a member leaking into
    # the config document fails loudly instead of writing an object tag.
    with pytest.raises(yaml.representer.RepresenterError):
        yaml.safe_dump({"step": StepEnum.STA})
