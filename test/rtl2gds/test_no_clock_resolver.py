"""Core no-clock decision and skip-policy boundary tests."""

from collections.abc import Mapping
from typing import cast

import pytest

from chipcompiler.data import DEFAULT_SKIP_STEPS
from chipcompiler.rtl2gds import NoClockDecision, resolve_no_clock, resolve_skip_steps

_NO_CLOCK_SKIPS = ("preplace", "diff_opt", "diff_sizing", "cts", "timing_optimization")
# Bypass the annotation deliberately so runtime caller-boundary validation is tested.
_INVALID_MATERIALS = cast(Mapping[str, object], ["clock_port"])


def test_explicit_true_wins_over_clock_material():
    assert resolve_no_clock({"no_clock": True}, materials={"clock_port": "clk"}) == NoClockDecision(
        enabled=True, source="explicit"
    )


@pytest.mark.parametrize("clock_port", ["", "   ", "\t\n"])
def test_explicit_false_overrides_empty_clock_inference(clock_port):
    assert resolve_no_clock({"no_clock": False}, materials={"clock_port": clock_port}) == (
        NoClockDecision(enabled=False, source="off")
    )


@pytest.mark.parametrize(
    "materials", [{}, {"clock_port": ""}, {"clock_port": " \t"}, {"clock": ""}]
)
def test_absent_empty_or_whitespace_clock_infers_no_clock(materials):
    assert resolve_no_clock({}, materials=materials) == NoClockDecision(
        enabled=True, source="inferred"
    )


@pytest.mark.parametrize("materials", [{"clock_port": " clk "}, {"clock": "clk"}])
def test_clock_name_disables_inference(materials):
    assert resolve_no_clock({}, materials=materials) == NoClockDecision(enabled=False, source="off")


def test_missing_materials_do_not_trigger_inference():
    assert resolve_no_clock({}) == NoClockDecision(enabled=False, source="off")


def test_clock_port_is_canonical_when_both_material_keys_are_present():
    assert resolve_no_clock({}, materials={"clock_port": "", "clock": "clk"}).enabled is True
    assert resolve_no_clock({}, materials={"clock_port": "clk", "clock": ""}).enabled is False


@pytest.mark.parametrize("flag", [None, 0, 1, 1.0, "true", "false", [], {}])
def test_invalid_no_clock_flag_types_are_rejected(flag):
    with pytest.raises(ValueError, match="no_clock must be a boolean"):
        resolve_no_clock({"no_clock": flag})


@pytest.mark.parametrize("clock", [None, 0, True, 1.5, ["clk"], {"name": "clk"}])
def test_invalid_clock_material_types_are_rejected(clock):
    with pytest.raises(ValueError, match="clock_port clock material must be a string"):
        resolve_no_clock({}, materials={"clock_port": clock})


def test_invalid_materials_container_is_rejected():
    with pytest.raises(ValueError, match="clock materials must be a mapping"):
        resolve_no_clock({}, materials=_INVALID_MATERIALS)


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        (True, NoClockDecision(enabled=True, source="explicit")),
        (False, NoClockDecision(enabled=False, source="off")),
    ],
)
def test_explicit_flag_precedence_does_not_inspect_materials(flag, expected):
    assert resolve_no_clock({"no_clock": flag}, materials=_INVALID_MATERIALS) == expected


@pytest.mark.parametrize("flow_config", [{}, {"skip_steps": []}])
def test_inferred_no_clock_folds_clock_dependent_skips(flow_config):
    assert resolve_skip_steps(flow_config, materials={"clock_port": ""}) == _NO_CLOCK_SKIPS


def test_explicit_no_clock_folds_skips_and_preserves_requested_steps():
    assert resolve_skip_steps(
        {"no_clock": True, "skip_steps": ["routing"]}, materials={"clock_port": "clk"}
    ) == (*_NO_CLOCK_SKIPS, "routing")


@pytest.mark.parametrize(
    ("flow_config", "expected"),
    [({"no_clock": False}, DEFAULT_SKIP_STEPS), ({"no_clock": False, "skip_steps": []}, ())],
)
def test_explicit_false_disables_no_clock_skip_folding(flow_config, expected):
    assert resolve_skip_steps(flow_config, materials={"clock_port": ""}) == expected


def test_retained_clock_preserves_existing_skip_policy():
    assert resolve_skip_steps({}, materials={"clock_port": "clk"}) == DEFAULT_SKIP_STEPS
    assert resolve_skip_steps({"skip_steps": []}, materials={"clock_port": "clk"}) == ()
