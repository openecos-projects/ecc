"""A step runs only with the design data it requires."""

from dataclasses import replace
from pathlib import Path

import pytest

from chipcompiler.data import EccStep, StepEnum
from chipcompiler.data.handshake import (
    DesignFiles,
    ResponseStatus,
    StepInputs,
    StepResponse,
    UpstreamResponse,
    missing_design_data,
    write_response,
)
from chipcompiler.data.types import AnalysisData, DesignState
from test.data.handshake.helpers import _LEGALIZED, _publish, _request, _route_request


def _answer(
    workspace,
    directory: str,
    *,
    status: ResponseStatus = ResponseStatus.SUCCESS,
    states: frozenset[DesignState] = frozenset(),
    outputs: dict[AnalysisData, tuple[Path, ...]] | None = None,
) -> UpstreamResponse:
    """Publish the response of the step in *directory*; return the link accepting it."""
    step, _separator, tool = directory.rpartition("_")
    write_response(
        workspace / directory,
        StepResponse(
            step=step,
            tool=tool,
            attempt_id=f"attempt-{step}",
            status=status,
            design=DesignFiles(),
            design_states=states,
            outputs=outputs or {},
            design_source=None,
            upstream={},
            warnings=frozenset(),
        ),
    )
    return UpstreamResponse(directory, f"attempt-{step}")


def test_an_upstream_step_that_has_not_answered_carries_nothing(tmp_path):
    request = _route_request(tmp_path, None)

    missing = missing_design_data(request, EccStep(name="routing"), declared_spef=None)

    assert missing == frozenset({DesignState.LEGAL})


def test_routing_after_cts_without_legalization_is_missing_a_legal_placement(tmp_path):
    clock_tree = (_LEGALIZED - {DesignState.LEGAL}) | {DesignState.CLOCK_TREE}
    _publish(tmp_path, "legalization_dreamplace", clock_tree)
    request = _route_request(tmp_path, "attempt-legal")

    missing = missing_design_data(request, EccStep(name="routing"), declared_spef=None)

    assert missing == frozenset({DesignState.LEGAL})


def test_without_an_rcx_step_parasitics_come_from_a_declared_spef(tmp_path):
    request = _request(tmp_path, StepEnum.STA.value, {})
    step = EccStep(name="sta")

    assert [
        missing_design_data(request, step, declared_spef=None),
        missing_design_data(request, step, declared_spef=tmp_path / "gcd.spef"),
    ] == [frozenset({AnalysisData.PARASITICS}), frozenset()]


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
    spef_files = tuple(tmp_path / "rcx_ecc" / "output" / name for name in spef)
    _answer(tmp_path, "rcx_ecc", status=status, outputs={AnalysisData.PARASITICS: spef_files})
    # The SPEF files a failed RCX left behind, wired onto STA as the parent does.
    for path in spef_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("*SPEF\n", encoding="utf-8")
    request = replace(
        _request(
            tmp_path,
            StepEnum.STA.value,
            {AnalysisData.PARASITICS: UpstreamResponse("rcx_ecc", accepted_attempt)},
        ),
        inputs=StepInputs(spef=spef_files),
    )

    assert missing_design_data(request, EccStep(name="sta"), declared_spef=None) == missing


def test_emir_needs_power_published_by_an_upstream_step(tmp_path):
    never_ran = _request(
        tmp_path,
        StepEnum.EMIR.value,
        {AnalysisData.POWER: UpstreamResponse("power_analysis_ecc", None)},
    )
    power = _answer(
        tmp_path,
        "power_analysis_ecc",
        outputs={AnalysisData.POWER: (tmp_path / "instance_power.tsv",)},
    )
    analyzed = _request(tmp_path, StepEnum.EMIR.value, {AnalysisData.POWER: power})
    step = EccStep(name="emir")

    assert [
        missing_design_data(_request(tmp_path, StepEnum.EMIR.value, {}), step, declared_spef=None),
        missing_design_data(never_ran, step, declared_spef=None),
        missing_design_data(analyzed, step, declared_spef=None),
    ] == [frozenset({AnalysisData.POWER}), frozenset({AnalysisData.POWER}), frozenset()]


def test_a_declared_design_entering_mid_chain_carries_the_states_built_before_it(tmp_path):
    from chipcompiler.data.flow_check import design_states_after
    from chipcompiler.data.handshake import input_design_states

    # An STA-entry flow: STA and power analysis run on the declared routed design.
    entry = input_design_states(_request(tmp_path, StepEnum.STA.value, {}))
    states = design_states_after(
        StepEnum.POWER_ANALYSIS.value, design_states_after(StepEnum.STA.value, entry)
    )
    power = _answer(
        tmp_path,
        "power_analysis_ecc",
        states=states,
        outputs={AnalysisData.POWER: (tmp_path / "instance_power.tsv",)},
    )
    request = _request(
        tmp_path,
        StepEnum.EMIR.value,
        {DesignState.FILLED: power, AnalysisData.POWER: power},
        design_source=power,
    )

    assert missing_design_data(request, EccStep(name="emir"), declared_spef=None) == frozenset()


def test_parasitics_source_names_where_the_step_reads_parasitics(tmp_path):
    from chipcompiler.data.handshake import ParasiticsSource, parasitics_source
    from chipcompiler.data.step import StepDirectories

    request = _request(tmp_path, StepEnum.STA.value, {})
    declared = tmp_path / "gcd.spef"
    inherited = StepDirectories.at(tmp_path).path(StepEnum.RCX.value) / "output"
    before_inheriting = [
        parasitics_source(request, declared_spef=None),
        parasitics_source(request, declared_spef=declared),
    ]
    inherited.mkdir(parents=True)
    (inherited / "gcd_TYPICAL_25C.spef").write_text("*SPEF\n", encoding="utf-8")
    rcx = _answer(tmp_path, "rcx_ecc", outputs={AnalysisData.PARASITICS: (inherited / "gcd.spef",)})
    from_rcx = _request(tmp_path, StepEnum.STA.value, {AnalysisData.PARASITICS: rcx})

    assert [
        *before_inheriting,
        parasitics_source(request, declared_spef=declared),
        parasitics_source(request, declared_spef=None),
        parasitics_source(from_rcx, declared_spef=declared),
    ] == [
        None,
        ParasiticsSource(None),
        ParasiticsSource(None),
        ParasiticsSource(inherited),
        ParasiticsSource(tmp_path / "rcx_ecc" / "output"),
    ]


def test_a_derived_workspace_reads_the_power_analysis_it_inherited(tmp_path):
    from chipcompiler.data.step import StepDirectories
    from chipcompiler.tools.ecc.power_artifacts import instance_power_path

    request = _request(tmp_path, StepEnum.EMIR.value, {})
    inherited = instance_power_path(
        StepDirectories.at(tmp_path).path(StepEnum.POWER_ANALYSIS.value)
    )
    inherited.parent.mkdir(parents=True)
    inherited.write_text("instance\tpower\n", encoding="utf-8")

    assert missing_design_data(request, EccStep(name="emir"), declared_spef=None) == frozenset()
