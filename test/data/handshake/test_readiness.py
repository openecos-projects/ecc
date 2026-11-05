"""A step runs only with the design data it requires."""

from chipcompiler.data import EccStep, StepEnum
from chipcompiler.data.handshake import (
    UpstreamResponse,
    missing_design_data,
)
from chipcompiler.data.types import AnalysisData, DesignState
from test.data.handshake.helpers import _LEGALIZED, _publish, _request, _route_request


def test_an_upstream_step_that_was_asked_to_run_but_never_answered_carries_nothing(tmp_path):
    (tmp_path / "legalization_dreamplace").mkdir()
    (tmp_path / "legalization_dreamplace" / "req.json").write_text("{}", encoding="utf-8")
    request = _route_request(tmp_path, None)

    missing = missing_design_data(request, EccStep(name="route"), declared_spef=None)

    assert missing == frozenset({DesignState.LEGAL})


def test_routing_after_cts_without_legalization_is_missing_a_legal_placement(tmp_path):
    clock_tree = (_LEGALIZED - {DesignState.LEGAL}) | {DesignState.CLOCK_TREE}
    _publish(tmp_path, "legalization_dreamplace", clock_tree)
    request = _route_request(tmp_path, "attempt-legal")

    missing = missing_design_data(request, EccStep(name="route"), declared_spef=None)

    assert missing == frozenset({DesignState.LEGAL})


def test_parasitics_come_from_rcx_or_a_declared_spef(tmp_path):
    filled = {DesignState.FILLED: UpstreamResponse("filler_ecc", None)}
    without_rcx = _request(tmp_path, StepEnum.STA.value, filled)
    with_rcx = _request(
        tmp_path,
        StepEnum.STA.value,
        {**filled, AnalysisData.PARASITICS: UpstreamResponse("RCX_ecc", None)},
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
