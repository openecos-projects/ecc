"""A step runs only with the design data it requires."""

import pytest

from chipcompiler.data import EccStep, StepEnum
from chipcompiler.data.handshake import (
    DesignFiles,
    ResponseStatus,
    StepResponse,
    UpstreamResponse,
    missing_design_data,
    write_response,
)
from chipcompiler.data.types import AnalysisData, DesignState
from test.data.handshake.helpers import _LEGALIZED, _publish, _request, _route_request


def test_an_upstream_step_that_was_asked_to_run_but_never_answered_carries_nothing(tmp_path):
    (tmp_path / "legalization_dreamplace").mkdir()
    (tmp_path / "legalization_dreamplace" / "req.json").write_text("{}", encoding="utf-8")
    request = _route_request(tmp_path, None)

    missing = missing_design_data(request, EccStep(name="routing"), declared_spef=None)

    assert missing == frozenset({DesignState.LEGAL})


def test_routing_after_cts_without_legalization_is_missing_a_legal_placement(tmp_path):
    clock_tree = (_LEGALIZED - {DesignState.LEGAL}) | {DesignState.CLOCK_TREE}
    _publish(tmp_path, "legalization_dreamplace", clock_tree)
    request = _route_request(tmp_path, "attempt-legal")

    missing = missing_design_data(request, EccStep(name="routing"), declared_spef=None)

    assert missing == frozenset({DesignState.LEGAL})


def test_parasitics_come_from_rcx_or_a_declared_spef(tmp_path):
    filled = {DesignState.FILLED: UpstreamResponse("filler_ecc", None)}
    without_rcx = _request(tmp_path, StepEnum.STA.value, filled)
    with_rcx = _request(
        tmp_path,
        StepEnum.STA.value,
        {**filled, AnalysisData.PARASITICS: UpstreamResponse("rcx_ecc", None)},
    )
    step = EccStep(name="sta")

    assert [
        missing_design_data(without_rcx, step, declared_spef=None),
        missing_design_data(without_rcx, step, declared_spef=tmp_path / "gcd.spef"),
        missing_design_data(with_rcx, step, declared_spef=None),
    ] == [frozenset({AnalysisData.PARASITICS}), frozenset(), frozenset()]


def test_emir_needs_power_from_an_upstream_step(tmp_path):
    request = _request(
        tmp_path, StepEnum.EMIR.value, {DesignState.FILLED: UpstreamResponse("filler_ecc", None)}
    )

    missing = missing_design_data(request, EccStep(name="emir"), declared_spef=None)

    assert missing == frozenset({AnalysisData.POWER})


def _publish_rcx(workspace, *, status: ResponseStatus, spef: tuple) -> None:
    write_response(
        workspace / "rcx_ecc",
        StepResponse(
            step="rcx",
            tool="ecc",
            attempt_id="attempt-rcx",
            status=status,
            design=DesignFiles(),
            design_states=frozenset(),
            outputs={AnalysisData.PARASITICS: spef},
            design_source=None,
            upstream={},
            warnings=frozenset(),
        ),
    )


@pytest.mark.parametrize(
    ("status", "spef", "accepted_attempt", "missing"),
    [
        (ResponseStatus.SUCCESS, ("gcd.spef",), "attempt-rcx", frozenset()),
        (ResponseStatus.FAILED, ("gcd.spef",), "attempt-rcx", {AnalysisData.PARASITICS}),
        (ResponseStatus.SUCCESS, (), "attempt-rcx", {AnalysisData.PARASITICS}),
        (ResponseStatus.SUCCESS, ("gcd.spef",), "attempt-earlier", {AnalysisData.PARASITICS}),
    ],
    ids=["published", "failed", "no spef", "another attempt"],
)
def test_parasitics_from_rcx_need_its_successful_response_for_the_accepted_run(
    tmp_path, status, spef, accepted_attempt, missing
):
    _publish_rcx(tmp_path, status=status, spef=tuple(tmp_path / name for name in spef))
    request = _request(
        tmp_path,
        StepEnum.STA.value,
        {
            DesignState.FILLED: UpstreamResponse("filler_ecc", None),
            AnalysisData.PARASITICS: UpstreamResponse("rcx_ecc", accepted_attempt),
        },
    )

    assert missing_design_data(request, EccStep(name="sta"), declared_spef=None) == missing


def test_a_declared_design_entering_mid_chain_carries_the_states_built_before_it(tmp_path):
    from chipcompiler.data.flow_check import design_states_after
    from chipcompiler.data.handshake import input_design_states

    # An STA-entry flow: STA and power analysis run on the declared routed design.
    entry = input_design_states(_request(tmp_path, StepEnum.STA.value, {}))
    states = design_states_after(
        StepEnum.POWER_ANALYSIS.value, design_states_after(StepEnum.STA.value, entry)
    )
    _publish(tmp_path, "power_analysis_ecc", states)
    power = UpstreamResponse("power_analysis_ecc", "attempt-legal")
    request = _request(
        tmp_path,
        StepEnum.EMIR.value,
        {
            DesignState.FILLED: power,
            AnalysisData.POWER: UpstreamResponse("power_analysis_ecc", None),
        },
        design_source=power,
    )

    assert missing_design_data(request, EccStep(name="emir"), declared_spef=None) == frozenset()
