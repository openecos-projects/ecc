"""The rsp.json a step publishes carries its design states, outputs and warnings."""

from chipcompiler.data import EccOutput, EccStep, StepEnum, YosysOutput, YosysStep
from chipcompiler.data.handshake import (
    DesignFiles,
    ResponseStatus,
    StepResponse,
    build_step_response,
    missing_design_data,
)
from chipcompiler.data.types import AnalysisData, DesignState
from test.data.handshake.helpers import _LEGALIZED, _publish, _request, _route_request


def test_routing_without_a_clock_tree_is_published_with_a_warning(tmp_path):
    _publish(tmp_path, "legalization_dreamplace", _LEGALIZED)
    request = _route_request(tmp_path, "attempt-legal")
    routed_def = tmp_path / "route_ecc" / "output" / "gcd_route.def.gz"
    routed_def.parent.mkdir(parents=True)
    routed_def.write_text("", encoding="utf-8")
    step = EccStep(name="route", output=EccOutput(def_=routed_def, verilog=tmp_path / "absent.v"))

    response = build_step_response(request, step, succeeded=True)

    assert response == StepResponse(
        step="route",
        tool="ecc",
        attempt_id="attempt-route",
        status=ResponseStatus.SUCCESS,
        design=DesignFiles(def_=routed_def),
        design_states=_LEGALIZED | {DesignState.ROUTED},
        outputs={},
        design_source=request.design_source,
        upstream=request.upstream,
        warnings=frozenset({DesignState.CLOCK_TREE}),
    )


def test_a_design_from_before_responses_is_trusted_to_carry_what_the_step_uses(tmp_path):
    request = _route_request(tmp_path, None)

    response = build_step_response(request, EccStep(name="route"), succeeded=True)

    assert (response.design_states, response.warnings) == (
        frozenset({DesignState.LEGAL, DesignState.CLOCK_TREE, DesignState.ROUTED}),
        frozenset(),
    )


def test_a_response_from_another_run_of_the_upstream_step_is_not_trusted(tmp_path):
    _publish(tmp_path, "legalization_dreamplace", _LEGALIZED)
    request = _route_request(tmp_path, "attempt-older")

    response = build_step_response(request, EccStep(name="route"), succeeded=True)

    assert response.design_states == frozenset({DesignState.ROUTED})
    assert missing_design_data(request, EccStep(name="route"), declared_spef=None) == frozenset(
        {DesignState.LEGAL}
    )


def test_rcx_publishes_its_parasitics(tmp_path):
    spef = (tmp_path / "RCX_ecc/output/gcd_rcworst_25C.spef",)
    request = _request(tmp_path, StepEnum.RCX.value, {})
    step = EccStep(name="RCX", output=EccOutput(spef=list(spef)))

    response = build_step_response(request, step, succeeded=True)

    assert response.outputs == {AnalysisData.PARASITICS: spef}


def test_a_failed_step_publishes_no_outputs(tmp_path):
    request = _request(tmp_path, StepEnum.RCX.value, {})
    step = EccStep(name="RCX", output=EccOutput(spef=[tmp_path / "x.spef"]))

    response = build_step_response(request, step, succeeded=False)

    assert (response.status, response.design, response.outputs, response.design_states) == (
        ResponseStatus.FAILED,
        DesignFiles(),
        {},
        frozenset(),
    )


def test_synthesis_publishes_the_golden_netlist(tmp_path):
    golden = tmp_path / "Synthesis_yosys/output/gcd_Synthesis_golden.v"
    request = _request(tmp_path, StepEnum.SYNTHESIS.value, {})
    step = YosysStep(name="Synthesis", output=YosysOutput(golden_verilog=golden))

    response = build_step_response(request, step, succeeded=True)

    assert response.outputs == {AnalysisData.GOLDEN_NETLIST: (golden,)}
